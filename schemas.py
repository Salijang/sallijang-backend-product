from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

class StoreBase(BaseModel):
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class StoreCreate(StoreBase):
    address: Optional[str] = None         # 기본 주소 (지오코딩에 사용)
    address_detail: Optional[str] = None  # 상세 주소 (표시용, 지오코딩 제외)

class StoreUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    address_detail: Optional[str] = None

class StoreResponse(StoreBase):
    id: int
    owner_id: int
    address: Optional[str] = None
    address_detail: Optional[str] = None
    avg_rating: float = 0.0
    review_count: int = 0
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReviewCreate(BaseModel):
    store_id: int
    order_id: int
    buyer_id: int
    rating: int
    content: str


class ReviewResponse(BaseModel):
    id: int
    store_id: int
    buyer_id: int
    order_id: int
    rating: int
    content: str
    store_name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ProductBase(BaseModel):
    name: str
    original_price: float
    discount_price: float
    remaining: int
    total_quantity: int
    expiry_minutes: int
    pickup_deadline: Optional[str] = None  # "HH:MM" 형식의 픽업 마감 시간
    category: str
    image_url: Optional[str] = None
    weight: Optional[str] = None
    description: Optional[str] = None
    is_deleted: bool = False

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    original_price: Optional[float] = None
    discount_price: Optional[float] = None
    remaining: Optional[int] = None
    total_quantity: Optional[int] = None
    expiry_minutes: Optional[int] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    weight: Optional[str] = None
    description: Optional[str] = None

class ProductResponse(ProductBase):
    id: int
    store_id: int
    created_at: datetime

    # 조인(Join)된 가게 데이터를 프론트엔드로 쉽게 넘겨주기 위함
    shop_name: Optional[str] = None
    store_address: Optional[str] = None
    store_address_detail: Optional[str] = None
    distance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)
