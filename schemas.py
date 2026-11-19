"""Modelos Pydantic del contrato HTTP de la API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, field_validator


def _no_solo_espacios(value: str) -> str:
    if not value.strip():
        raise ValueError("El texto no puede contener solo espacios.")
    return value


class AskIn(BaseModel):
    pregunta: str = Field(min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    auto_aprobar: StrictBool = True

    @field_validator("pregunta", "thread_id")
    @classmethod
    def validar_texto(cls, value: str | None) -> str | None:
        return _no_solo_espacios(value) if value is not None else None


class AskOut(BaseModel):
    respuesta: str
    thread_id: str
    done: bool
    pendiente_hitl: bool
    error: str | None = None


class ApproveIn(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    aprobado: StrictBool

    @field_validator("thread_id")
    @classmethod
    def validar_thread_id(cls, value: str) -> str:
        return _no_solo_espacios(value)


class MessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
