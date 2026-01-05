import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, Query, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, select, desc
)
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession
)
from sqlalchemy.orm import declarative_base, sessionmaker

from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest

from dotenv import load_dotenv
load_dotenv() 

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "telegram")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./data/data.db"
)

CACHE_HOURS = int(os.getenv("CACHE_HOURS", 24))

# ---------------- DB ----------------
Base = declarative_base()

class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    channel_username = Column(String, index=True)
    message_id = Column(Integer)
    text = Column(Text)
    date = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)

# ---------------- TELETHON ----------------
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
# ---------------- UTILITIES ----------------
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_db()
    await client.start()
    yield

def is_cache_valid(fetched_at: datetime) -> bool:
    return fetched_at > datetime.utcnow() - timedelta(hours=CACHE_HOURS)


# ---------------- APP ----------------
app = FastAPI(lifespan=lifespan)

# Disable uvicorn default error logging
# logging.getLogger("uvicorn.error").disabled = True


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Return clean response, no traceback
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )

# ---------------- TELEGRAM FETCH ----------------
async def fetch_and_store_all(username: str) -> tuple[int, int]:
    read_count = 0
    stored_count = 0

    async with AsyncSessionLocal() as db:
        offset_id = 0
        limit = 100

        while True:
            history = await client(
                GetHistoryRequest(
                    peer=username,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )

            if not history.messages:
                break

            for msg in history.messages:
                read_count += 1

                if not msg.message:
                    continue

                exists = await db.execute(
                    select(Post).where(
                        Post.channel_username == username,
                        Post.message_id == msg.id
                    )
                )
                if exists.scalar_one_or_none():
                    continue

                db.add(Post(
                    channel_username=username,
                    message_id=msg.id,
                    text=msg.message,
                    date=msg.date,
                    fetched_at=datetime.utcnow()
                ))
                stored_count += 1

            await db.commit()
            offset_id = history.messages[-1].id

    return read_count, stored_count

# ---------------- ROUTES ----------------

@app.post("/save-all")
async def save_all(
    username: str = Query(...),
    background_tasks: BackgroundTasks = None
):
    background_tasks.add_task(fetch_and_store_all, username)
    return {"status": "started", "username": username}


@app.get("/read")
async def read_posts(
    username: str = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100)
):
    async with AsyncSessionLocal() as db:
        offset = (page - 1) * per_page

        result = await db.execute(
            select(Post)
            .where(Post.channel_username == username)
            .order_by(desc(Post.date))
            .offset(offset)
            .limit(per_page)
        )

        posts = result.scalars().all()

        # اگر دیتای تازه نداشت، از تلگرام بگیر
        if not posts or not is_cache_valid(posts[0].fetched_at):
            await fetch_and_store_all(username)
            return await read_posts(username, page, per_page)

        return [
            {
                "message_id": p.message_id,
                "text": p.text,
                "date": p.date
            }
            for p in posts
        ]


@app.get("/read-all")
async def read_all(username: str = Query(...)):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post)
            .where(Post.channel_username == username)
            .order_by(desc(Post.date))
        )
        posts = result.scalars().all()

        if not posts or not is_cache_valid(posts[0].fetched_at):
            read_count, stored_count = await fetch_and_store_all(username)

            print(
                f"[READ-ALL] Channel: {username} | "
                f"Read from Telegram: {read_count} | "
                f"Stored in SQLite: {stored_count}"
            )

            return await read_all(username)

        print(
            f"[READ-ALL] Channel: {username} | "
            f"Returned from cache: {len(posts)} posts"
        )

        return [
            {
                "message_id": p.message_id,
                "text": p.text,
                "date": p.date
            }
            for p in posts
        ]
