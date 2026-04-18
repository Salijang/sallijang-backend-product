from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import httpx

KAKAO_REST_API_KEY = "83d69d138d85ef5e80b27f425bbbe0f2"

async def geocode_address(address: str) -> Optional[tuple[float, float]]:
    """카카오 로컬 API로 주소를 위도/경도로 변환합니다."""
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {"query": address, "analyze_type": "similar"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers, timeout=8.0)
            print(f"[geocode] status={resp.status_code} body={resp.text[:300]}")
            data = resp.json()
            docs = data.get("documents", [])
            if docs:
                # x = 경도(longitude), y = 위도(latitude)
                return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None

from database import get_db
import models
import schemas

router = APIRouter(prefix="/api/v1/stores", tags=["Stores"])

@router.post("/", response_model=schemas.StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(store: schemas.StoreCreate, owner_id: int, db: AsyncSession = Depends(get_db)):
    print(f"[create_store] 수신된 데이터: name={store.name}, address={store.address}, address_detail={store.address_detail}, lat={store.latitude}, lng={store.longitude}")
    
    lat, lng = store.latitude, store.longitude

    if store.address and not (lat and lng):
        import re
        print(f"[create_store] 주소 지오코딩 시도: {store.address}")
        result = await geocode_address(store.address)
        # 결과 없으면 "지하"/"지상" 제거 후 재시도
        if not result:
            fallback = re.sub(r'\s*(?:지하|지상)\s*', ' ', store.address).strip()
            fallback = re.sub(r'\s+', ' ', fallback)
            print(f"[create_store] 지오코딩 재시도 (fallback): {fallback}")
            result = await geocode_address(fallback)
        print(f"[create_store] 지오코딩 결과: {result}")
        if result:
            lat, lng = result
    
    print(f"[create_store] 최종 저장 좌표: lat={lat}, lng={lng}")
    new_store = models.Store(
        owner_id=owner_id,
        name=store.name,
        address=store.address,
        address_detail=store.address_detail or None,
        distance=store.distance,
        latitude=lat,
        longitude=lng
    )
    db.add(new_store)
    await db.commit()
    await db.refresh(new_store)
    return new_store

@router.get("/", response_model=List[schemas.StoreResponse])
async def list_stores(owner_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    query = select(models.Store)
    if owner_id:
        query = query.filter(models.Store.owner_id == owner_id)
    result = await db.execute(query)
    return result.scalars().all()

@router.patch("/{store_id}", response_model=schemas.StoreResponse)
async def update_store(store_id: int, store_update: schemas.StoreUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Store).filter(models.Store.id == store_id))
    store = result.scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if store_update.name is not None:
        store.name = store_update.name
    if store_update.address_detail is not None:
        store.address_detail = store_update.address_detail
    if store_update.address is not None:
        store.address = store_update.address
        import re
        print(f"[update_store] 재지오코딩 시도: {store_update.address}")
        coords = await geocode_address(store_update.address)
        if not coords:
            fallback = re.sub(r'\s*(?:지하|지상)\s*', ' ', store_update.address).strip()
            fallback = re.sub(r'\s+', ' ', fallback)
            print(f"[update_store] 재지오코딩 재시도 (fallback): {fallback}")
            coords = await geocode_address(fallback)
        print(f"[update_store] 지오코딩 결과: {coords}")
        if coords:
            store.latitude, store.longitude = coords

    await db.commit()
    await db.refresh(store)
    return store
