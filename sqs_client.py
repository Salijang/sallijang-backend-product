import asyncio
import boto3
import json
import os
from botocore.config import Config

STOCK_RESULT_QUEUE_URL = os.getenv("STOCK_RESULT_QUEUE_URL", "")
AWS_REGION             = os.getenv("AWS_REGION", "ap-northeast-2")

_BOTO_CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
_sqs_client = None


def _get_sqs():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _sqs_client


async def publish_stock_result(payload: dict) -> None:
    if not STOCK_RESULT_QUEUE_URL:
        return
    def _send():
        _get_sqs().send_message(QueueUrl=STOCK_RESULT_QUEUE_URL, MessageBody=json.dumps(payload))
    try:
        await asyncio.to_thread(_send)
    except Exception as e:
        print(f"[SQS] publish_stock_result 실패: {e}")
