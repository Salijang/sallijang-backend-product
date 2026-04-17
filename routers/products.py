from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.orm import selectinload
from typing import List, Optional
import math

def calculate_distance_km(lat1, lon1, lat2, lon2):
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float('inf')
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def format_distance(km):
    if km == float('inf'):
        return "거리 알 수 없음"
    m = km * 1000
    if m < 1000:
        return f"{int(m)}m"
    return f"{km:.1f}km"

from database import get_db
import models
import schemas

router = APIRouter(prefix="/api/v1/products", tags=["Products"])

@router.post("/", response_model=schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(product: schemas.ProductCreate, store_id: int, db: AsyncSession = Depends(get_db)):
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
    response_data.distance = store.distance

    return response_data

@router.get("/", response_model=List[schemas.ProductResponse])
async def list_products(
    store_id: Optional[int] = None,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    # N+1 쿼리 방지를 위해 selectinload 로 Store 관련 정보도 함께 가져옵니다
    # 논리적으로 삭제된 항목은 제외하고, remaining > 0 인 상품만 조회합니다
    query = select(models.Product).options(selectinload(models.Product.store)).filter(
        models.Product.is_deleted == False,
        models.Product.remaining > 0
    )
    if store_id:
        query = query.filter(models.Product.store_id == store_id)

    # 페이지네이션 적용
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    products = result.scalars().all()

    response_list = []
    for p in products:
        p_resp = schemas.ProductResponse.model_validate(p)
        dist_val = 0
        if p.store:
            p_resp.shop_name = p.store.name
            p_resp.store_address = p.store.address
            if user_lat is not None and user_lng is not None:
                dist_km = calculate_distance_km(user_lat, user_lng, p.store.latitude, p.store.longitude)
                p_resp.distance = format_distance(dist_km)
                dist_val = dist_km
            else:
                p_resp.distance = p.store.distance
                dist_val = float('inf') # user loc not given, preserve original order

            p_resp.latitude = p.store.latitude
            p_resp.longitude = p.store.longitude
        response_list.append((p_resp, dist_val))

    if user_lat is not None and user_lng is not None:
        response_list.sort(key=lambda x: x[1])

    return [item[0] for item in response_list]

@router.get("/{product_id}", response_model=schemas.ProductResponse)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
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
        p_resp.distance = product.store.distance
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
        p_resp.distance = product.store.distance
    return p_resp

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
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
