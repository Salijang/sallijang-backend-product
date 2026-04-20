from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional

from database import get_db
import models
import schemas

router = APIRouter(prefix="/api/v1/reviews", tags=["Reviews"])


@router.post("/", response_model=schemas.ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(review: schemas.ReviewCreate, db: AsyncSession = Depends(get_db)):
    """리뷰를 작성합니다. 같은 order_id로 중복 작성은 불가합니다."""
    store_result = await db.execute(select(models.Store).filter(models.Store.id == review.store_id))
    store = store_result.scalars().first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    dup = await db.execute(
        select(models.Review).filter(models.Review.order_id == review.order_id)
    )
    if dup.scalars().first():
        raise HTTPException(status_code=409, detail="Review already exists for this order")

    if not (1 <= review.rating <= 5):
        raise HTTPException(status_code=422, detail="Rating must be between 1 and 5")

    new_review = models.Review(
        store_id=review.store_id,
        buyer_id=review.buyer_id,
        order_id=review.order_id,
        rating=review.rating,
        content=review.content,
    )
    db.add(new_review)

    total_rating = (store.avg_rating * store.review_count) + review.rating
    store.review_count += 1
    store.avg_rating = round(total_rating / store.review_count, 1)

    await db.commit()
    await db.refresh(new_review)

    result = schemas.ReviewResponse(
        id=new_review.id,
        store_id=new_review.store_id,
        buyer_id=new_review.buyer_id,
        order_id=new_review.order_id,
        rating=new_review.rating,
        content=new_review.content,
        store_name=store.name,
        created_at=new_review.created_at,
    )
    return result


@router.get("/", response_model=List[schemas.ReviewResponse])
async def list_reviews(
    store_id: Optional[int] = None,
    buyer_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """리뷰 목록 조회. store_id 또는 buyer_id로 필터링합니다."""
    query = select(models.Review, models.Store.name).join(
        models.Store, models.Review.store_id == models.Store.id
    )
    if store_id:
        query = query.filter(models.Review.store_id == store_id)
    if buyer_id:
        query = query.filter(models.Review.buyer_id == buyer_id)
    query = query.order_by(models.Review.created_at.desc())

    result = await db.execute(query)
    rows = result.all()

    return [
        schemas.ReviewResponse(
            id=r.id,
            store_id=r.store_id,
            buyer_id=r.buyer_id,
            order_id=r.order_id,
            rating=r.rating,
            content=r.content,
            store_name=store_name,
            created_at=r.created_at,
        )
        for r, store_name in rows
    ]


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(review_id: int, db: AsyncSession = Depends(get_db)):
    """리뷰를 삭제하고 가게 평균 별점을 재계산합니다."""
    result = await db.execute(select(models.Review).filter(models.Review.id == review_id))
    review = result.scalars().first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    store_result = await db.execute(select(models.Store).filter(models.Store.id == review.store_id))
    store = store_result.scalars().first()

    if store and store.review_count > 1:
        total_rating = (store.avg_rating * store.review_count) - review.rating
        store.review_count -= 1
        store.avg_rating = round(total_rating / store.review_count, 1)
    elif store:
        store.review_count = 0
        store.avg_rating = 0.0

    await db.delete(review)
    await db.commit()
