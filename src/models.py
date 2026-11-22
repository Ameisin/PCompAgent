
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    thread_id: str = Field(primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)

    thread_id: str = Field(
        foreign_key="conversations.thread_id",
        index=True
    )

    role: str
    content: str

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
