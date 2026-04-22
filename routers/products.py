from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime
import math

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
import models
import schemas

router = APIRouter(prefix="/api/v1/products", tags=["Products"])

@router.post("/", response_model=schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(product: schemas.ProductCreate, store_id: int, db: AsyncSession = Depends(get_db)):
    """가게에 새 상품을 등록합니다. 존재하지 않는 store_id 입력 시 404를 반환합니다."""
    # 등록 전 가게(Store)가 실제로 존재하는지 검증
    result = await db.execute(select(models.Store).filter(models.Store.id == store_id))
    store = result.scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    new_product = models.Product(**product.model_dump(), store_id=store_id)
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)

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
    query = (
        select(models.Product)
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

    # 위치 정보가 있으면 DB에서 거리 계산 후 정렬 → LIMIT/OFFSET 적용
    if user_lat is not None and user_lng is not None:
        dist_expr = _haversine_expr(user_lat, user_lng)
        query = query.order_by(dist_expr)

    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    products = result.scalars().all()

    response_list = []
    for p in products:
        p_resp = schemas.ProductResponse.model_validate(p)
        if p.store:
            p_resp.shop_name = p.store.name
            p_resp.store_address = p.store.address
            p_resp.store_address_detail = p.store.address_detail
            if user_lat is not None and user_lng is not None and p.store.latitude and p.store.longitude:
                dlat = math.radians(p.store.latitude - user_lat)
                dlng = math.radians(p.store.longitude - user_lng)
                a = math.sin(dlat/2)**2 + math.cos(math.radians(user_lat)) * math.cos(math.radians(p.store.latitude)) * math.sin(dlng/2)**2
                dist_km = 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                p_resp.distance = format_distance(dist_km)
            else:
                p_resp.distance = None
            p_resp.latitude = p.store.latitude
            p_resp.longitude = p.store.longitude
        response_list.append(p_resp)

    return response_list

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
    return {"product_id": product_id, "remaining": row[0]}

@router.patch("/{product_id}", response_model=schemas.ProductResponse)
async def update_product(product_id: int, product_update: schemas.ProductUpdate, db: AsyncSession = Depends(get_db)):
    """상품 정보를 수정합니다. 전달된 필드만 선택적으로 업데이트합니다."""
    result = await db.execute(select(models.Product).options(selectinload(models.Product.store)).filter(
        models.Product.id == product_id,
        models.Product.is_deleted == False
    ))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    update_data = product_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)
        
    await db.commit()
    await db.refresh(product)
    
    p_resp = schemas.ProductResponse.model_validate(product)
    if product.store:
        p_resp.shop_name = product.store.name
        p_resp.store_address = product.store.address
        p_resp.distance = None
    return p_resp

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    """상품을 소프트 삭제합니다 (is_deleted=True). 실제 DB 레코드는 보존됩니다."""
    result = await db.execute(select(models.Product).filter(
        models.Product.id == product_id,
        models.Product.is_deleted == False
    ))
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    product.is_deleted = True
    await db.commit()
    return None
