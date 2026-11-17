"""API HTTP del agente PcComponentes."""

import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from schemas import ApproveIn, AskIn, AskOut
from src.agent import aprobar_plan, nuevo_thread_id, procesar_turno
from src.state import crear_estado

app = FastAPI(
    title="Asistente PcComponentes API",
    description="API REST para el agente multiagente de PcComponentes.",
    version="1.0.0",
)

# El checkpoint de LangGraph y este estado de producto viven en memoria del proceso.
_estados_por_thread: dict[str, dict[str, Any]] = {}


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
    estado = _estados_por_thread.get(thread_id) or crear_estado(request.pregunta)
    habia_hitl_pendiente = bool(estado.get("pendiente_hitl"))
    estado = procesar_turno(estado, request.pregunta, thread_id)

    if request.auto_aprobar and not habia_hitl_pendiente and estado.get("pendiente_hitl"):
        estado = aprobar_plan(thread_id, True, estado)

    estado["thread_id"] = thread_id
    _estados_por_thread[thread_id] = estado
    return _respuesta_api(estado, thread_id)


@app.post("/approve", response_model=AskOut, dependencies=[Depends(requerir_api_key)])
def approve(request: ApproveIn) -> AskOut:
    estado = _estados_por_thread.get(request.thread_id)
    if estado is None:
        estado = crear_estado()
        estado["respuesta"] = "No hay un plan pendiente de aprobación para este thread_id."
    else:
        estado = aprobar_plan(request.thread_id, request.aprobado, estado)

    estado["thread_id"] = request.thread_id
    _estados_por_thread[request.thread_id] = estado
    return _respuesta_api(estado, request.thread_id)
