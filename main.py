from fastapi import FastAPI
import contextlib
from database import engine
from routers import stores, products, reviews

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()

# User Service와 차별화를 위해 메타데이터 정의
app = FastAPI(
    title="Sallijang Product Service",
    description="Microservice for interacting with Sellers' Stores and their discounted Products.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(stores.router)
app.include_router(products.router)
app.include_router(reviews.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Sallijang Product Service API! Go to http://localhost:8001/docs to test endpoints."}
