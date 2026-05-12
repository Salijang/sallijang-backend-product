import asyncio
import boto3
import json
import os
from sqlalchemy.future import select
from sqlalchemy import update
from botocore.config import Config
from database import SessionLocal
from sqs_client import publish_stock_result
import models

STOCK_DEDUCT_QUEUE_URL = os.getenv("STOCK_DEDUCT_QUEUE_URL", "")
AWS_REGION             = os.getenv("AWS_REGION", "ap-northeast-2")

_BOTO_CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2})
_sqs_client = None


def _get_sqs():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _sqs_client


async def _deduct_stock(product_id: int, quantity: int) -> bool:
    from redis_client import set_stock
    async with SessionLocal() as db:
        stmt = (
            update(models.Product)
            .where(
                models.Product.id == product_id,
                models.Product.is_deleted == False,
                models.Product.remaining + (-quantity) >= 0,
            )
            .values(remaining=models.Product.remaining + (-quantity))
            .returning(models.Product.remaining)
        )
        result = await db.execute(stmt)
        row = result.fetchone()
        if row is None:
            await db.rollback()
            return False
        await db.commit()
        await set_stock(product_id, row[0])
        return True


async def process_stock_deduct(body: dict) -> None:
    if body.get("event_type") != "stock_deduct":
        return

    order_id = body.get("order_id")
    items = body.get("items", [])
    failed_items = []

    for item in items:
        success = await _deduct_stock(item["product_id"], item["quantity"])
        if not success:
            failed_items.append(item)
            print(f"[Saga] 재고 차감 실패 — product_id={item['product_id']}, order_id={order_id}")

    if failed_items:
        await publish_stock_result({
            "event_type": "stock_failed",
            "order_id": order_id,
            "items": failed_items,
        })


async def start_consumer() -> None:
    if not STOCK_DEDUCT_QUEUE_URL:
        print("[SQS StockDeduct] STOCK_DEDUCT_QUEUE_URL 미설정 — 비활성화")
        return

    def _receive():
        return _get_sqs().receive_message(
            QueueUrl=STOCK_DEDUCT_QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )

    def _delete(receipt_handle: str):
        _get_sqs().delete_message(QueueUrl=STOCK_DEDUCT_QUEUE_URL, ReceiptHandle=receipt_handle)

    async def _handle_message(msg: dict) -> None:
        body = json.loads(msg["Body"])
        await process_stock_deduct(body)
        await asyncio.to_thread(_delete, msg["ReceiptHandle"])

    print("[SQS StockDeduct] 소비자 시작")
    while True:
        try:
            response = await asyncio.to_thread(_receive)
            messages = response.get("Messages", [])
            if not messages:
                continue
            results = await asyncio.gather(
                *[_handle_message(msg) for msg in messages],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    # 메시지를 삭제하지 않아 visibility timeout 후 SQS가 자동 재시도
                    print(f"[SQS StockDeduct] 메시지 처리 실패 (재시도 예약): {result}")
        except asyncio.CancelledError:
            print("[SQS StockDeduct] 종료")
            return
        except Exception as e:
            print(f"[SQS StockDeduct] 오류: {e}")
            await asyncio.sleep(5)
