"""Tools PROVISIONALES para poder ejecutar el grafo en la rama feature/grafo-hitl.

Las tools definitivas (RAG, API externa, auxiliar y multimodal) las desarrolla el
equipo en sus ramas, en el paquete src/tools/ con el contrato de clase:

    from src.tools import TOOLS, ejecutar_tool

Mientras ese paquete no exista, src/registro_tools.py carga este módulo, que
ofrece el mínimo para que el grafo funcione de punta a punta:

  - RAG_consultar_catalogo → envuelve responder() del RAG completo del PB1
    (ChromaDB + Gemini, con abstención fuera de corpus).
  - hora_actual           → auxiliar determinista (idéntica a la de clase).

Mismo patrón que el Sprint 12: allowlist + validar_args + ejecutar_tool.
"""

import re
import time
from datetime import datetime

from langchain_core.tools import tool

import config as config_rag


def _segundos_espera_429(error: Exception) -> float | None:
    """Si el error es un 429 POR MINUTO de Gemini, devuelve la espera que pide el servidor.

    Devuelve None (no reintentar) si no es un 429 o si es el límite DIARIO
    (quotaId «...PerDay...»): esperar unos segundos no lo resuelve.
    El mensaje trae «Please retry in 38.08s» o «'retryDelay': '38s'».
    """
    texto = str(error)
    if "429" not in texto and "RESOURCE_EXHAUSTED" not in texto:
        return None
    if "PerDay" in texto:
        return None
    m = re.search(r"retry in ([\d.]+)s", texto) or re.search(r"retryDelay'?:\s*'([\d.]+)s", texto)
    return float(m.group(1)) + 1 if m else 30.0


@tool
def RAG_consultar_catalogo(consulta: str, top_k: int = 5) -> str:
    """Consulta el RAG del catálogo de componentes de PC, compatibilidades,
    guías de compra/montaje y requisitos de videojuegos. Devuelve una respuesta
    anclada al corpus con sus fuentes. Haz consultas concretas, p. ej.
    'procesadores AM5 por menos de 200 dólares' o 'requisitos de Cyberpunk 2077'.
    """
    # Import diferido: logic arrastra Chroma y el cliente de Gemini; así el
    # grafo se puede compilar y verificar sin cargar el índice.
    from logic import responder

    from src import config_grafo
    from src.llm import limitador

    # Mismo limitador que el agente si generan con el mismo modelo (misma cuota).
    modelo = config_grafo.RAG_GEMINI_MODEL
    rpm = config_grafo.LLM_RPM if modelo == config_grafo.GEMINI_MODEL else config_grafo.RAG_RPM
    limitador(modelo, rpm).acquire()
    try:
        resultado = responder(consulta, top_k=top_k, modelo=modelo)
    except Exception as e:  # noqa: BLE001
        espera = _segundos_espera_429(e)
        if espera is None:
            raise
        # 429 por minuto: un único reintento tras la espera que indica el servidor.
        time.sleep(min(espera, config_grafo.RAG_ESPERA_MAX_429_S))
        resultado = responder(consulta, top_k=top_k, modelo=modelo)
    if resultado.get("error"):
        return f"Error: {resultado['error']}"
    fuentes = ", ".join(resultado.get("fuentes") or []) or "(sin fuentes)"
    return f"{resultado.get('respuesta') or '(sin respuesta)'}\n\nFuentes: {fuentes}"


@tool
def hora_actual() -> str:
    """Devuelve la fecha y hora local actuales en formato ISO."""
    return datetime.now().isoformat(timespec="seconds")


TOOLS = [RAG_consultar_catalogo, hora_actual]

# Allowlist: solo se ejecuta lo registrado aquí.
TOOL_BY_NAME = {t.name: t for t in TOOLS}


def validar_args(nombre: str, args: dict | None = None) -> dict:
    """Guardrails antes de ejecutar (tipos, límites y vacíos)."""
    args = args or {}
    if nombre == "hora_actual":
        return {}
    if nombre == "RAG_consultar_catalogo":
        try:
            top_k = int(args.get("top_k") or config_rag.TOP_K)
        except (TypeError, ValueError):
            top_k = config_rag.TOP_K
        return {
            "consulta": str(args.get("consulta") or "").strip()[: config_rag.LONGITUD_MAX_PREGUNTA],
            "top_k": max(1, min(top_k, 10)),
        }
    return args


def ejecutar_tool(nombre: str, args: dict | None = None) -> str:
    """Ejecuta una tool de la allowlist; si no está, la bloquea."""
    tool_fn = TOOL_BY_NAME.get(nombre)
    if tool_fn is None:
        return f"Error: tool '{nombre}' no está permitida."
    limpios = validar_args(nombre, args)
    if nombre == "RAG_consultar_catalogo" and not limpios.get("consulta"):
        return "Error: la consulta al RAG no puede estar vacía."
    try:
        return str(tool_fn.invoke(limpios))
    except Exception as e:  # noqa: BLE001
        return f"Error al ejecutar {nombre}: {e}"
