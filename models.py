from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def kst_now() -> datetime:
    """현재 한국 표준시(KST, UTC+9)를 반환합니다."""
    return datetime.now(KST).replace(tzinfo=None)

class Store(Base):
    __tablename__ = "stores"
    __table_args__ = {'schema': 'product_schema'}

    id = Column(Integer, primary_key=True, index=True)
    # MSA 설계 원칙에 따라, 타 마이크로서비스(사용자)의 테이블과 하드한 물리적 외래키 연결을 피하고
    # 논리적으로만 owner_id를 저장하여 결합도(Coupling)를 낮춥니다.
    owner_id = Column(Integer, index=True, nullable=False)
    name = Column(String, index=True, nullable=False)
    address = Column(String, nullable=True)
    distance = Column(String, nullable=True) # 예: "500m"
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=kst_now)

    products = relationship("Product", back_populates="store")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = {'schema': 'product_schema'}

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("product_schema.stores.id"), index=True, nullable=False)
    name = Column(String, index=True, nullable=False)
    original_price = Column(Float, nullable=False)
    discount_price = Column(Float, nullable=False)
    remaining = Column(Integer, default=0)
    total_quantity = Column(Integer, default=0)
    expiry_minutes = Column(Integer, default=60)
    pickup_deadline = Column(String, nullable=True)  # 픽업 마감 날짜/시간 "YYYY-MM-DDTHH:MM" 형식
    category = Column(String, index=True)
    image_url = Column(String, nullable=True)
    weight = Column(String, nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=kst_now)
    is_deleted = Column(Boolean, default=False)

    store = relationship("Store", back_populates="products")
