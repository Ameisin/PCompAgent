"""API HTTP del agente PcComponentes."""

import json
import logging
import os
import secrets
import time
from _thread import LockType
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi


from schemas import ApproveIn, AskIn, AskOut, MessageOut
from src import config_grafo
from src.agent import aprobar_plan, nuevo_thread_id, procesar_turno
from src.state import crear_estado

app = FastAPI(
    title="Asistente PcComponentes API",
    description="API REST para el agente multiagente de PcComponentes.",
    version="1.0.0",
)

# CORS: orígenes permitidos desde CORS_ORIGINS (separados por comas).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
        if o.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

@app.middleware("http")
async def registrar_peticion(request: Request, call_next):
    """Un log por petición: método, ruta (sin query), thread_id, status y duración."""
    inicio = time.perf_counter()
    response = await call_next(request)
    duracion_ms = round((time.perf_counter() - inicio) * 1000, 1)
    log.info(json.dumps({
        "metodo": request.method,
        "ruta": request.url.path,
        "thread_id": getattr(request.state, "thread_id", None),
        "status": response.status_code,
        "duration_ms": duracion_ms,
    }))
    return response

# El checkpoint de LangGraph y este estado de producto viven en memoria del proceso.
_estados_por_thread: dict[str, dict[str, Any]] = {}


@dataclass
class _BloqueoHilo:
    lock: LockType = field(default_factory=Lock)
    usuarios: int = 0


_locks_por_thread: dict[str, _BloqueoHilo] = {}
_locks_guard = Lock()

# Rate limit en memoria: marcas de tiempo de las peticiones por API key.
_ventanas: dict[str, deque[float]] = defaultdict(deque)
_ventanas_lock = Lock()

# Timeout: el turno del agente corre en un hilo y se espera un máximo de tiempo.
_executor = ThreadPoolExecutor(max_workers=8)

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

def limitar_tasa(api_key: str | None = Query(default=None)) -> None:
    limite = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    ahora = time.monotonic()
    with _ventanas_lock:
        ventana = _ventanas[api_key or "anonimo"]
        while ventana and ahora - ventana[0] > 60:
            ventana.popleft()
        if len(ventana) >= limite:
            raise HTTPException(
                status_code=429,
                detail="Demasiadas peticiones. Espera un minuto.",
                headers={"Retry-After": "60"},
            )
        ventana.append(ahora)
        

def _con_timeout(fn: Callable[..., AskOut], *args: Any) -> AskOut:
    """Ejecuta fn en un hilo y devuelve 504 si supera ASK_TIMEOUT_SECONDS."""
    futuro = _executor.submit(fn, *args)
    try:
        return futuro.result(timeout=float(os.getenv("ASK_TIMEOUT_SECONDS", "300")))
    except FutureTimeout:
        # El hilo sigue ejecutándose en segundo plano; no se puede cancelar.
        raise HTTPException(status_code=504, detail="El turno superó ASK_TIMEOUT_SECONDS.")
        
        

def _respuesta_api(estado: dict[str, Any], thread_id: str) -> AskOut:
    return AskOut(
        respuesta=str(estado.get("respuesta") or ""),
        thread_id=thread_id,
        done=bool(estado.get("done")),
        pendiente_hitl=bool(estado.get("pendiente_hitl")),
        error=estado.get("error"),
    )


def _ejecutar_ask(cuerpo: AskIn, http: Request) -> AskOut:
    thread_id = cuerpo.thread_id or nuevo_thread_id()
    http.state.thread_id = thread_id  # lo lee el middleware de logs
    with _lock_thread(thread_id):
        estado = _estados_por_thread.get(thread_id) or crear_estado(cuerpo.pregunta)
        habia_hitl_pendiente = bool(estado.get("pendiente_hitl"))
        estado = procesar_turno(
            estado, cuerpo.pregunta, thread_id, max_turns=config_grafo.MAX_TURNS_DEFAULT
        )

        if cuerpo.auto_aprobar and not habia_hitl_pendiente and estado.get("pendiente_hitl"):
            estado = aprobar_plan(thread_id, True, estado)

        estado["thread_id"] = thread_id
        _estados_por_thread[thread_id] = estado
        return _respuesta_api(estado, thread_id)


def _ejecutar_approve(cuerpo: ApproveIn, http: Request) -> AskOut:
    http.state.thread_id = cuerpo.thread_id
    with _lock_thread(cuerpo.thread_id):
        estado = _estados_por_thread.get(cuerpo.thread_id)
        if estado is None:
            estado = crear_estado()
            estado["respuesta"] = "No hay un plan pendiente de aprobación para este thread_id."
            return _respuesta_api(estado, cuerpo.thread_id)
        estado = aprobar_plan(cuerpo.thread_id, cuerpo.aprobado, estado)
        estado["thread_id"] = cuerpo.thread_id
        _estados_por_thread[cuerpo.thread_id] = estado
        return _respuesta_api(estado, cuerpo.thread_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskOut, dependencies=[Depends(requerir_api_key)])
def ask(request: AskIn) -> AskOut:
    thread_id = request.thread_id or nuevo_thread_id()
    with _lock_thread(thread_id):
        estado = _estados_por_thread.get(thread_id) or crear_estado(request.pregunta)
        habia_hitl_pendiente = bool(estado.get("pendiente_hitl"))
        estado = procesar_turno(
            estado, request.pregunta, thread_id, max_turns=config_grafo.MAX_TURNS_DEFAULT
        )

        if request.auto_aprobar and not habia_hitl_pendiente and estado.get("pendiente_hitl"):
            estado = aprobar_plan(thread_id, True, estado)

        estado["thread_id"] = thread_id
        _estados_por_thread[thread_id] = estado
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
