import asyncio
import contextlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine
from routers import stores, products, reviews
from sqs_consumer import start_consumer


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    consumer_task = asyncio.create_task(start_consumer())
    yield
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(
    title="Sallijang Product Service",
    description="Microservice for interacting with Sellers' Stores and their discounted Products.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sallijang.shop"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stores.router)
app.include_router(products.router)
app.include_router(reviews.router)


@app.get("/")
def read_root():
    return {"message": "Welcome to Sallijang Product Service API! Go to http://localhost:8001/docs to test endpoints."}


@app.get("/health")
def health():
    return {"status": "ok"}
