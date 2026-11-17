"""Modelos Pydantic del contrato HTTP de la API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AskIn(BaseModel):
    pregunta: str = Field(min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, min_length=1)
    auto_aprobar: bool = True


class AskOut(BaseModel):
    respuesta: str
    thread_id: str
    done: bool
    pendiente_hitl: bool
    error: str | None = None


class ApproveIn(BaseModel):
    thread_id: str = Field(min_length=1)
    aprobado: bool


class MessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
