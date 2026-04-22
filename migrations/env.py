import os
import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool, text
from alembic import context

from database import Base
import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    import boto3
    from urllib.parse import quote_plus
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "adminuser")
    db = os.environ.get("DB_NAME", "pickupdb")
    region = os.environ.get("AWS_REGION", "ap-northeast-2")
    token = boto3.client("rds", region_name=region).generate_db_auth_token(
        DBHostname=host, Port=int(port), DBUsername=user
    )
    return f"postgresql+asyncpg://{user}:{quote_plus(token)}@{host}:{port}/{db}"


def include_name(name, type_, parent_names):
    del parent_names
    if type_ == "schema":
        return name == "product_schema"
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS product_schema"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema="product_schema",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        get_url(),
        poolclass=pool.NullPool,
        connect_args={"ssl": "require"},
    )
    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
