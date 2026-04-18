from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import httpx

async def geocode_address(address: str) -> Optional[tuple[float, float]]:
    """
    OpenStreetMap Nominatim API로 주소를 위도/경도로 변환합니다.
    심사 불필요, API Key 불필요, 완전 무료.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "countrycodes": "kr",  # 한국 주소로 범위 제한
    }
    headers = {
        # Nominatim 이용관인 상 User-Agent 필수 명시
        "User-Agent": "Salijang/1.0 (contact@salijang.com)",
        "Accept-Language": "ko",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers, timeout=8.0)
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
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
    
    # 주소가 입력된 경우 Nominatim으로 위도/경도 자동 추출
    # "지하", "지상" 등 Nominatim이 인식 못하는 키워드 제거 후 지오코딩
    import re
    geocode_address_str = re.sub(r'\s*지하\s*|\s*지상\s*', ' ', store.address or '').strip() if store.address else ''
    geocode_address_str = re.sub(r'\s+', ' ', geocode_address_str)
    if geocode_address_str and not (lat and lng):
        print(f"[create_store] 주소 지오코딩 시도: {geocode_address_str}")
        result = await geocode_address(geocode_address_str)
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
        # 주소가 바뀌었으면 재지오코딩
        import re
        geocode_str = re.sub(r'\s*지하\s*|\s*지상\s*', ' ', store_update.address).strip()
        geocode_str = re.sub(r'\s+', ' ', geocode_str)
        print(f"[update_store] 재지오코딩 시도: {geocode_str}")
        coords = await geocode_address(geocode_str)
        print(f"[update_store] 지오코딩 결과: {coords}")
        if coords:
            store.latitude, store.longitude = coords

    await db.commit()
    await db.refresh(store)
    return store
