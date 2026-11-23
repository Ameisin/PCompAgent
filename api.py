"""API HTTP del agente PcComponentes."""

import logging
import os
import secrets
from _thread import LockType
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.openapi.utils import get_openapi

from schemas import ApproveIn, AskIn, AskOut, MessageOut
from src import config_grafo
from src.agent import aprobar_plan, nuevo_thread_id, procesar_turno
from src.state import crear_estado
from src.repository import guardar_turno, obtener_historial_api

app = FastAPI(
    title="Asistente PcComponentes API",
    description="API REST para el agente multiagente de PcComponentes.",
    version="1.0.0",
)

# El checkpoint de LangGraph y este estado de producto viven en memoria del proceso.
_estados_por_thread: dict[str, dict[str, Any]] = {}


@dataclass
class _BloqueoHilo:
    lock: LockType = field(default_factory=Lock)
    usuarios: int = 0


_locks_por_thread: dict[str, _BloqueoHilo] = {}
_locks_guard = Lock()


class _OcultarQueryEnAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn registra el path con query en el tercer argumento del access log.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = args[2].partition("?")[0]
                record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(_OcultarQueryEnAccessLog())


@contextmanager
def _lock_thread(thread_id: str) -> Iterator[None]:
    with _locks_guard:
        bloqueo = _locks_por_thread.setdefault(thread_id, _BloqueoHilo())
        bloqueo.usuarios += 1
    try:
        with bloqueo.lock:
            yield
    finally:
        with _locks_guard:
            bloqueo.usuarios -= 1
            if bloqueo.usuarios == 0:
                del _locks_por_thread[thread_id]


def _openapi() -> dict[str, Any]:
    if app.openapi_schema is None:
        schema = get_openapi(
            title=app.title, version=app.version, description=app.description, routes=app.routes
        )
        schema.setdefault("components", {}).setdefault("schemas", {})["MessageOut"] = (
            MessageOut.model_json_schema()
        )
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _openapi


def requerir_api_key(api_key: str | None = Query(default=None)) -> None:
    """Valida la clave enviada como query parameter."""
    api_key_configurada = os.getenv("API_KEY")
    if not api_key_configurada:
        raise HTTPException(
            status_code=503,
            detail="La API no tiene API_KEY configurada.",
        )
    if api_key is None or not secrets.compare_digest(
        api_key.encode("utf-8"),
        api_key_configurada.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="API key ausente o incorrecta.")


def _respuesta_api(estado: dict[str, Any], thread_id: str) -> AskOut:
    return AskOut(
        respuesta=str(estado.get("respuesta") or ""),
        thread_id=thread_id,
        done=bool(estado.get("done")),
        pendiente_hitl=bool(estado.get("pendiente_hitl")),
        error=estado.get("error"),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}



@app.post("/ask", response_model=AskOut, dependencies=[Depends(requerir_api_key)])
def ask(request: AskIn) -> AskOut:
    thread_id = request.thread_id or nuevo_thread_id()

    with _lock_thread(thread_id):
        estado = _estados_por_thread.get(thread_id) or crear_estado(request.pregunta)

        habia_hitl_pendiente = bool(estado.get("pendiente_hitl"))
        numero_turnos_antes = len(estado.get("traza") or [])

        estado = procesar_turno(
            estado,
            request.pregunta,
            thread_id,
            max_turns=config_grafo.MAX_TURNS_DEFAULT
        )

        # Comprobar si el agente ha procesado un nuevo turno
        traza_nueva = (estado.get("traza") or [])[numero_turnos_antes:]
        turno_procesado = any(
            turno.get("status") == "ok"
            and turno.get("mensaje") == request.pregunta.strip()
            for turno in traza_nueva
        )

        if (
            request.auto_aprobar
            and not habia_hitl_pendiente
            and estado.get("pendiente_hitl")
        ):
            estado = aprobar_plan(thread_id, True, estado)

        estado["thread_id"] = thread_id
        _estados_por_thread[thread_id] = estado

        # Guardar solo los turnos procesados correctamente
        if turno_procesado and not estado.get("error"):
            guardar_turno(
                thread_id=thread_id,
                pregunta=request.pregunta,
                respuesta=str(estado.get("respuesta") or "")
            )

        return _respuesta_api(estado, thread_id)


@app.post("/approve", response_model=AskOut, dependencies=[Depends(requerir_api_key)])
def approve(request: ApproveIn) -> AskOut:
    with _lock_thread(request.thread_id):
        estado = _estados_por_thread.get(request.thread_id)
        if estado is None:
            estado = crear_estado()
            estado["respuesta"] = "No hay un plan pendiente de aprobación para este thread_id."
            return _respuesta_api(estado, request.thread_id)
        else:
            estado = aprobar_plan(request.thread_id, request.aprobado, estado)

        estado["thread_id"] = request.thread_id
        _estados_por_thread[request.thread_id] = estado
        return _respuesta_api(estado, request.thread_id)

@app.get(
    "/threads/{thread_id}/messages",
    response_model=list[MessageOut],
    dependencies=[Depends(requerir_api_key)]
)
def obtener_historial(thread_id: str) -> list[MessageOut]:
    """
    Recupera los mensajes de una conversación desde PostgreSQL.
    """
    mensajes = obtener_historial_api(thread_id)
    return [MessageOut(**mensaje) for mensaje in mensajes]
