from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime
import asyncio
import math
import uuid
import os
import base64
import json
import re
import boto3
import httpx

def format_distance(km: float) -> str:
    """거리(km)를 사람이 읽기 쉬운 문자열(m 또는 km)로 변환합니다."""
    if km == float('inf'):
        return "거리 알 수 없음"
    m = km * 1000
    if m < 1000:
        return f"{int(m)}m"
    return f"{km:.1f}km"

def _haversine_expr(user_lat: float, user_lng: float):
    """DB에서 실행되는 Haversine 거리 계산 SQL 표현식 (단위: km)"""
    return (
        6371.0 * func.acos(
            func.least(1.0,
                func.cos(func.radians(user_lat)) *
                func.cos(func.radians(models.Store.latitude)) *
                func.cos(func.radians(models.Store.longitude) - func.radians(user_lng)) +
                func.sin(func.radians(user_lat)) *
                func.sin(func.radians(models.Store.latitude))
            )
        )
    )

from database import get_db
from deps import get_current_user, CurrentUser
from redis_client import set_stock, get_redis, publish_product_update
import models
import schemas

router = APIRouter(prefix="/api/v1/products", tags=["Products"])

_IMAGE_BUCKET = os.getenv("IMAGE_BUCKET_NAME", "")
_CDN_URL = os.getenv("CDN_URL", "https://cdn.sallijang.shop")

@router.get("/upload-url")
async def get_upload_url(
    file_type: str = Query(default="image/jpeg"),
    current_user: CurrentUser = Depends(get_current_user),
):
    ext = "jpg" if "jpeg" in file_type else file_type.split("/")[-1]
    key = f"products/{uuid.uuid4()}.{ext}"
    region = os.getenv("AWS_REGION", "ap-northeast-2")
    s3 = boto3.client("s3", region_name=region, endpoint_url=f"https://s3.{region}.amazonaws.com")
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": _IMAGE_BUCKET, "Key": key, "ContentType": file_type},
        ExpiresIn=300,
    )
    return {"upload_url": upload_url, "key": key, "cdn_url": f"{_CDN_URL}/{key}"}


_BEDROCK_SUPPORTED_MEDIA = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_CATEGORIES = ["🥩 정육", "🥬 채소", "🐟 수산", "🍱 반찬", "🥐 베이커리"]

@router.post("/analyze-image")
async def analyze_product_image(
    body: schemas.ImageAnalyzeRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """상품 사진을 Bedrock Claude로 분석해 상품명·설명·카테고리를 자동 생성합니다."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            img_res = await client.get(body.image_url)
            img_res.raise_for_status()
        except Exception:
            raise HTTPException(status_code=400, detail="이미지를 가져올 수 없습니다.")

    if len(img_res.content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="이미지 크기가 너무 큽니다 (5MB 이하).")

    media_type = img_res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if media_type not in _BEDROCK_SUPPORTED_MEDIA:
        media_type = "image/jpeg"

    image_b64 = base64.standard_b64encode(img_res.content).decode()

    categories_str = ", ".join(_CATEGORIES)
    prompt = (
        f"이 사진이 음식·식재료·반찬·베이커리 등 먹을 수 있는 것인지 먼저 판단하세요.\n"
        f"음식 사진이 아니면 반드시 {{\"error\": \"not_food\"}} 만 응답하세요.\n"
        f"음식 사진이면 다음 JSON만 응답하세요 (다른 말 없이):\n"
        f"{{\"name\": \"상품명\", \"description\": \"2~3문장 설명 (신선도·상태·특징)\", \"category\": \"{categories_str} 중 하나\"}}"
    )

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    }

    bedrock_region = os.getenv("BEDROCK_REGION", "us-east-1")
    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=bedrock_region)
        resp = await asyncio.to_thread(
            bedrock.invoke_model, modelId=model_id, body=json.dumps(payload)
        )
        raw_text = json.loads(resp["body"].read())["content"][0]["text"].strip()
        raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
        raw_text = re.sub(r"\n?```$", "", raw_text.strip())
        data = json.loads(raw_text)
        if data.get("error") == "not_food":
            raise HTTPException(status_code=422, detail="음식 사진이 아닙니다. 음식 또는 식재료 사진을 업로드해 주세요.")
        category = data.get("category", "")
        if category not in _CATEGORIES:
            category = ""
        return {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "category": category,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 분석 실패: {str(e)}")


@router.post("/", response_model=schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product: schemas.ProductCreate,
    store_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """가게에 새 상품을 등록합니다. 존재하지 않는 store_id 입력 시 404를 반환합니다."""
    # 등록 전 가게(Store)가 실제로 존재하는지 검증
    result = await db.execute(select(models.Store).filter(models.Store.id == store_id))
    store = result.scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if store.owner_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    new_product = models.Product(**product.model_dump(), store_id=store_id)
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)

    await set_stock(new_product.id, new_product.remaining)
    await publish_product_update(new_product.id, new_product.remaining)

    # 응답 스키마에 프론트엔드가 요구하는 가게 이름(shop_name) 정보를 결합하여 반환
    response_data = schemas.ProductResponse.model_validate(new_product)
    response_data.shop_name = store.name
    response_data.store_address = store.address
    response_data.distance = None

    return response_data

@router.get("/", response_model=List[schemas.ProductResponse])
async def list_products(
    store_id: Optional[int] = None,
    category: Optional[str] = None,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """상품 목록을 조회합니다. store_id로 특정 가게 필터, user_lat/lng 제공 시 거리 순 정렬.
    store_id 미지정(buyer 조회) 시 픽업 마감이 지난 상품은 자동 제외됩니다."""
    has_location = user_lat is not None and user_lng is not None

    if has_location:
        dist_expr = _haversine_expr(user_lat, user_lng).label("distance_km")
        base_select = select(models.Product, dist_expr)
    else:
        base_select = select(models.Product)

    query = (
        base_select
        .options(selectinload(models.Product.store))
        .join(models.Store, models.Product.store_id == models.Store.id)
        .filter(
            models.Product.is_deleted == False,
            models.Product.remaining > 0,
        )
    )

    if store_id:
        query = query.filter(models.Product.store_id == store_id)
    else:
        # buyer 조회: 픽업 마감이 지난 상품 제외
        # "YYYY-MM-DDTHH:MM" 형식만 비교 (길이 <= 5 이면 구형 "HH:MM" 형식 → 표시 유지)
        now_str = datetime.now().strftime('%Y-%m-%dT%H:%M')
        query = query.filter(
            or_(
                models.Product.pickup_deadline == None,
                models.Product.pickup_deadline == '',
                func.length(models.Product.pickup_deadline) <= 5,
                models.Product.pickup_deadline >= now_str,
            )
        )

    if category:
        query = query.filter(models.Product.category == category)

    if has_location:
        query = query.order_by(dist_expr)

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)

    # 위치 있을 때: (Product, distance_km) 튜플, 없을 때: Product만
    if has_location:
        rows = result.all()
    else:
        rows = [(p, None) for p in result.scalars().all()]

    response_list = []
    for p, dist_km in rows:
        p_resp = schemas.ProductResponse.model_validate(p)
        if p.store:
            p_resp.shop_name = p.store.name
            p_resp.store_address = p.store.address
            p_resp.store_address_detail = p.store.address_detail
            p_resp.distance = format_distance(dist_km) if dist_km is not None else None
            p_resp.latitude = p.store.latitude
            p_resp.longitude = p.store.longitude
        response_list.append(p_resp)

    return response_list

@router.get("/stream")
async def stream_product_updates(request: Request):
    async def generator():
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe("sse:products")
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if message:
                    yield f"data: {message['data']}\n\n"
                else:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe("sse:products")
            await pubsub.aclose()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{product_id}", response_model=schemas.ProductResponse)
async def get_product(
    product_id: int,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
):
    """단일 상품을 조회합니다. user_lat/lng 제공 시 가게까지의 거리를 계산하여 반환합니다."""
    result = await db.execute(select(models.Product).options(selectinload(models.Product.store)).filter(
        models.Product.id == product_id,
        models.Product.is_deleted == False
    ))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    p_resp = schemas.ProductResponse.model_validate(product)
    if product.store:
        p_resp.shop_name = product.store.name
        p_resp.store_address = product.store.address
        p_resp.store_address_detail = product.store.address_detail
        p_resp.latitude = product.store.latitude
        p_resp.longitude = product.store.longitude
        if user_lat is not None and user_lng is not None and product.store.latitude and product.store.longitude:
            dlat = math.radians(product.store.latitude - user_lat)
            dlng = math.radians(product.store.longitude - user_lng)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(user_lat)) * math.cos(math.radians(product.store.latitude)) * math.sin(dlng/2)**2
            dist_km = 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            p_resp.distance = format_distance(dist_km)
        else:
            p_resp.distance = None
    return p_resp

@router.patch("/{product_id}/remaining")
async def adjust_remaining(product_id: int, delta: int, db: AsyncSession = Depends(get_db)):
    """재고 수량을 delta만큼 조정합니다. 음수=감소, 양수=복원.
    remaining + delta >= 0 조건을 UPDATE WHERE에 걸어 원자적으로 처리합니다."""
    stmt = (
        update(models.Product)
        .where(
            models.Product.id == product_id,
            models.Product.is_deleted == False,
            models.Product.remaining + delta >= 0,
        )
        .values(remaining=models.Product.remaining + delta)
        .returning(models.Product.remaining)
    )
    result = await db.execute(stmt)
    row = result.fetchone()

    if row is None:
        await db.rollback()
        # 상품 자체가 없는지 vs 재고 부족인지 구분
        exists = await db.execute(
            select(models.Product.remaining).filter(
                models.Product.id == product_id,
                models.Product.is_deleted == False,
            )
        )
        product_row = exists.first()
        if product_row is None:
            raise HTTPException(status_code=404, detail="Product not found")
        raise HTTPException(
            status_code=409,
            detail=f"재고가 부족합니다. 현재 남은 수량: {product_row[0]}개",
        )

    await db.commit()
    await set_stock(product_id, row[0])
    await publish_product_update(product_id, row[0])
    return {"product_id": product_id, "remaining": row[0]}


@router.patch("/{product_id}", response_model=schemas.ProductResponse)
async def update_product(
    product_id: int,
    product_update: schemas.ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """상품 정보를 수정합니다. 전달된 필드만 선택적으로 업데이트합니다."""
    result = await db.execute(select(models.Product).options(selectinload(models.Product.store)).filter(
        models.Product.id == product_id,
        models.Product.is_deleted == False
    ))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.store and product.store.owner_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    update_data = product_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)

    if "remaining" in update_data:
        await set_stock(product.id, product.remaining)
    await publish_product_update(product.id, product.remaining, action="updated")

    p_resp = schemas.ProductResponse.model_validate(product)
    if product.store:
        p_resp.shop_name = product.store.name
        p_resp.store_address = product.store.address
        p_resp.distance = None
    return p_resp

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """상품을 소프트 삭제합니다 (is_deleted=True). 실제 DB 레코드는 보존됩니다."""
    result = await db.execute(select(models.Product).options(selectinload(models.Product.store)).filter(
        models.Product.id == product_id,
        models.Product.is_deleted == False
    ))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.store and product.store.owner_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    product.is_deleted = True
    await db.commit()
    await publish_product_update(product_id, -1, action="deleted")
    return None
