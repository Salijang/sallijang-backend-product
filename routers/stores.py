from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from database import get_db
import models
import schemas

router = APIRouter(prefix="/api/v1/stores", tags=["Stores"])

@router.post("/", response_model=schemas.StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(store: schemas.StoreCreate, owner_id: int, db: AsyncSession = Depends(get_db)):
    # Note: 실무 MSA 환경에서는 API Gateway를 거치며 검증된 JWT 토큰 내부에서 owner_id를 꺼냅니다.
    # 지금은 테스트를 위해 명시적으로 owner_id를 파라미터로 받습니다.
    new_store = models.Store(
        owner_id=owner_id, 
        name=store.name,
        distance=store.distance
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
