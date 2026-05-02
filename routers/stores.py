from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import httpx
import re
import os

from database import get_db
from deps import get_current_user, CurrentUser
import models
import schemas

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "83d69d138d85ef5e80b27f425bbbe0f2")

router = APIRouter(prefix="/api/v1/stores", tags=["Stores"])


async def geocode_address(address: str) -> Optional[tuple[float, float]]:
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {"query": address, "analyze_type": "similar"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=headers, timeout=8.0)
            docs = resp.json().get("documents", [])
            if docs:
                return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None


async def geocode_with_fallback(address: str) -> Optional[tuple[float, float]]:
    result = await geocode_address(address)
    if not result:
        fallback = re.sub(r'\s*(?:지하|지상)\s*', ' ', address).strip()
        fallback = re.sub(r'\s+', ' ', fallback)
        result = await geocode_address(fallback)
    return result


@router.post("/", response_model=schemas.StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    store: schemas.StoreCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    lat, lng = store.latitude, store.longitude

    if store.address and not (lat and lng):
        coords = await geocode_with_fallback(store.address)
        if coords:
            lat, lng = coords

    new_store = models.Store(
        owner_id=current_user.user_id,
        name=store.name,
        address=store.address,
        address_detail=store.address_detail or None,
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


@router.get("/{store_id}", response_model=schemas.StoreResponse)
async def get_store(store_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Store).filter(models.Store.id == store_id))
    store = result.scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


@router.patch("/{store_id}", response_model=schemas.StoreResponse)
async def update_store(
    store_id: int,
    store_update: schemas.StoreUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    result = await db.execute(select(models.Store).filter(models.Store.id == store_id))
    store = result.scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if store.owner_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if store_update.name is not None:
        store.name = store_update.name
    if store_update.address_detail is not None:
        store.address_detail = store_update.address_detail
    if store_update.address is not None:
        store.address = store_update.address
        coords = await geocode_with_fallback(store_update.address)
        if coords:
            store.latitude, store.longitude = coords

    await db.commit()
    await db.refresh(store)
    return store
