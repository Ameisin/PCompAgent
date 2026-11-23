"""Comprobaciones del despliegue (PB3, parte 4: Docker + Render).

Uso:
  python verificar_despliegue.py
      Revisa el repositorio sin red y sin LLM: Dockerfile, .dockerignore,
      requirements, variables de .env.example, RAG dentro de la imagen y
      que no haya secretos versionados. Es lo que miramos antes de cada deploy.

  python verificar_despliegue.py --url https://<servicio>.onrender.com
      Prueba de humo contra la API (local o Render) sin gastar LLM:
      /health, /docs y 401 sin clave. Si API_KEY está en el entorno (.env),
      también lee el historial de un hilo.

  python verificar_despliegue.py --url ... --ask --thread prueba-vida-1
      Además lanza un /ask real (gasta cuota de Gemini) y comprueba que el
      turno queda en GET /threads/{thread_id}/messages.

  python verificar_despliegue.py --url ... --thread prueba-vida-1
      Después de un redeploy: el historial de ese hilo tiene que seguir ahí.

La API key se lee de la variable API_KEY (o del .env). No se pasa por la línea
de comandos y no se imprime nunca, ni dentro de una URL.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

# Variables que tienen que estar en el panel de Render (y documentadas en .env.example)
VARIABLES_RENDER = [
    "DATABASE_URL",
    "API_KEY",
    "GEMINI_API_KEY",
    "CORS_ORIGINS",
    "ASK_TIMEOUT_SECONDS",
    "RATE_LIMIT_PER_MINUTE",
]

PREGUNTA_DEMO = (
    "Ya tengo un Ryzen con socket AM4, ¿qué placa base y RAM me recomiendas "
    "por menos de 150 USD?"
)

# Tiempos de espera del cliente. El free tier de Render puede tardar en despertar.
TIMEOUT_HEALTH = 120
TIMEOUT_RUTA = 30
TIMEOUT_ASK = 330  # algo más que ASK_TIMEOUT_SECONDS=300 del servicio

# Patrones de secretos: clave de Gemini y connection string con contraseña a un host no local
PATRON_GEMINI = re.compile(r"AIza[0-9A-Za-z_\-]{35}")
PATRON_DB = re.compile(
    r"postgres(?:ql)?://[^:\s/]+:[^@\s]+@(?!127\.0\.0\.1|localhost|host\.docker\.internal)"
)
EXTENSIONES_TEXTO = {".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".json", ".example", ".cfg", ".ini"}


# --------------------------------------------------------------------------
# 1) Revisión estática del repositorio (sin red, sin LLM)
# --------------------------------------------------------------------------

def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else ""


def _ficheros_versionados() -> list[str]:
    try:
        salida = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return salida.stdout.splitlines()


def revisar_repositorio() -> list[str]:
    fallos: list[str] = []

    # Dockerfile: una imagen que escucha en 0.0.0.0 y respeta PORT
    df = _leer(ROOT / "Dockerfile")
    if not df:
        fallos.append("Falta Dockerfile")
    else:
        if "0.0.0.0" not in df:
            fallos.append("Dockerfile: uvicorn tiene que escuchar en 0.0.0.0")
        if "${PORT:-8000}" not in df:
            fallos.append("Dockerfile: el puerto tiene que ser ${PORT:-8000}")
        if "api:app" not in df:
            fallos.append("Dockerfile: el CMD tiene que arrancar api:app")

    # .dockerignore: sin secretos, sin entorno virtual y sin .git
    di = _leer(ROOT / ".dockerignore").splitlines()
    if not di:
        fallos.append("Falta .dockerignore")
    else:
        for patron in (".env", ".venv", ".git"):
            if patron not in di:
                fallos.append(f".dockerignore: falta {patron}")

    # requirements: lo que necesita la API y sin torch (imagen de varios GB)
    req = _leer(ROOT / "requirements.txt").lower()
    for paquete in ("fastapi", "uvicorn", "sqlmodel", "psycopg"):
        if paquete not in req:
            fallos.append(f"requirements.txt: falta {paquete}")
    if re.search(r"^torch==", req, flags=re.M):
        fallos.append("requirements.txt: sobra torch (solo hace falta para embeddings locales)")

    # .env.example: las variables que van al panel de Render
    env_ejemplo = _leer(ROOT / ".env.example")
    for variable in VARIABLES_RENDER:
        if not re.search(rf"^#?\s*{variable}=", env_ejemplo, flags=re.M):
            fallos.append(f".env.example: falta {variable}")

    # El RAG viaja dentro de la imagen: corpus, índice e imagen demo
    if not (ROOT / "api.py").is_file():
        fallos.append("Falta api.py (la API FastAPI)")
    if not (ROOT / "chroma" / "chroma.sqlite3").is_file():
        fallos.append("Falta el índice del RAG en chroma/ (python main.py --index)")
    if not list((ROOT / "data" / "csv").glob("*.csv")):
        fallos.append("Faltan los CSV del catálogo en data/csv/")
    if not (ROOT / "assets" / "imagen_demo.jpg").is_file():
        fallos.append("Falta assets/imagen_demo.jpg (tool multimodal)")

    # Sin secretos en el repositorio
    versionados = _ficheros_versionados()
    if ".env" in versionados:
        fallos.append(".env está versionado: sacadlo con git rm --cached .env")
    for nombre in versionados:
        ruta = ROOT / nombre
        if ruta.suffix not in EXTENSIONES_TEXTO or not ruta.is_file():
            continue
        if ruta.stat().st_size > 1_000_000:  # embeddings y similares
            continue
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        if PATRON_GEMINI.search(texto):
            fallos.append(f"Posible clave de Gemini en {nombre}")
        if PATRON_DB.search(texto):
            fallos.append(f"Posible connection string con contraseña en {nombre}")

    return fallos


# --------------------------------------------------------------------------
# 2) Prueba de humo contra la API (local o Render)
# --------------------------------------------------------------------------

def _peticion(metodo: str, base: str, ruta: str, timeout: int, **kwargs):
    """Hace la petición y devuelve (respuesta, segundos).

    Si falla la conexión no relanzamos la excepción: su mensaje puede incluir
    la URL con ?api_key=. Devolvemos None y solo se imprime la ruta.
    """
    inicio = time.perf_counter()
    try:
        respuesta = requests.request(metodo, base + ruta, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        print(f"  {metodo} {ruta}: sin respuesta ({type(exc).__name__})")
        return None, time.perf_counter() - inicio
    return respuesta, time.perf_counter() - inicio


def _mensajes(base: str, thread_id: str, api_key: str, fallos: list[str]) -> list[dict] | None:
    """Lee el historial del hilo. Devuelve None si la petición falla."""
    r, seg = _peticion(
        "GET", base, f"/threads/{thread_id}/messages", TIMEOUT_RUTA, params={"api_key": api_key}
    )
    if r is None or r.status_code != 200:
        fallos.append(f"GET /threads/{thread_id}/messages con clave: {getattr(r, 'status_code', 'sin respuesta')}")
        return None
    mensajes = r.json()
    print(f"  GET /threads/{thread_id}/messages -> 200, {len(mensajes)} mensajes ({seg:.1f} s)")
    for m in mensajes:
        texto = str(m.get("content", "")).replace("\n", " ")
        print(f"     [{m.get('role')}] {m.get('created_at', '')} {texto[:90]}")
    return mensajes


def probar_api(base: str, thread_id: str, lanzar_ask: bool) -> list[str]:
    fallos: list[str] = []
    base = base.rstrip("/")
    api_key = (os.getenv("API_KEY") or "").strip()
    print(f"API: {base}")

    # /health sin clave. La primera petición mide el cold start del free tier.
    r, seg = _peticion("GET", base, "/health", TIMEOUT_HEALTH)
    if r is None or r.status_code != 200:
        fallos.append(f"/health: {getattr(r, 'status_code', 'sin respuesta')}")
        return fallos  # si no hay servicio, el resto no tiene sentido
    datos = r.json()
    print(f"  GET /health -> 200 {datos} ({seg:.1f} s)")
    if datos.get("storage") != "postgres":
        fallos.append(f"/health no indica storage=postgres: {datos}")

    # Swagger abierto sin clave
    r, seg = _peticion("GET", base, "/docs", TIMEOUT_RUTA)
    if r is None or r.status_code != 200:
        fallos.append(f"/docs: {getattr(r, 'status_code', 'sin respuesta')}")
    else:
        print(f"  GET /docs -> 200 ({seg:.1f} s)")

    # Rutas protegidas sin clave -> 401 (body válido, para no confundirlo con un 422)
    body = {"pregunta": PREGUNTA_DEMO, "thread_id": thread_id, "auto_aprobar": True}
    for metodo, ruta, kwargs in (
        ("POST", "/ask", {"json": body}),
        ("GET", f"/threads/{thread_id}/messages", {}),
    ):
        r, _ = _peticion(metodo, base, ruta, TIMEOUT_RUTA, **kwargs)
        codigo = getattr(r, "status_code", "sin respuesta")
        print(f"  {metodo} {ruta} sin clave -> {codigo}")
        if codigo != 401:
            fallos.append(f"{metodo} {ruta} sin clave debería dar 401 y da {codigo}")

    if not api_key:
        print("  (sin API_KEY en el entorno: no se prueban las rutas con clave)")
        if lanzar_ask:
            fallos.append("--ask necesita API_KEY en el entorno o en .env")
        return fallos

    if lanzar_ask:
        print(f"  POST /ask (thread_id={thread_id}), puede tardar unos minutos...")
        r, seg = _peticion(
            "POST", base, "/ask", TIMEOUT_ASK, params={"api_key": api_key}, json=body
        )
        if r is None or r.status_code != 200:
            fallos.append(f"POST /ask con clave: {getattr(r, 'status_code', 'sin respuesta')}")
        else:
            out = r.json()
            print(
                f"  POST /ask -> 200 en {seg:.0f} s: done={out.get('done')} "
                f"pendiente_hitl={out.get('pendiente_hitl')} error={out.get('error')}"
            )
            print("     " + str(out.get("respuesta", ""))[:300].replace("\n", "\n     "))
            if not out.get("done"):
                fallos.append("El /ask con auto_aprobar=true no ha quedado cerrado (done=false)")

    mensajes = _mensajes(base, thread_id, api_key, fallos)
    if mensajes == [] and (lanzar_ask or thread_id != "humo"):
        fallos.append(f"El hilo {thread_id} no tiene mensajes en Postgres")
    return fallos


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Comprobaciones del despliegue")
    parser.add_argument("--url", default=os.getenv("API_BASE_URL"), help="URL base de la API")
    parser.add_argument("--thread", default="humo", help="thread_id para /ask y el historial")
    parser.add_argument("--ask", action="store_true", help="lanza un /ask real (gasta cuota)")
    parser.add_argument("--solo-api", action="store_true", help="no revisa el repositorio")
    args = parser.parse_args()

    fallos: list[str] = []
    if not args.solo_api:
        print("Repositorio:")
        fallos_repo = revisar_repositorio()
        print("  OK" if not fallos_repo else f"  {len(fallos_repo)} pendientes")
        fallos += fallos_repo
    if args.url:
        fallos += probar_api(args.url, args.thread, args.ask)

    if fallos:
        print("\nPendiente:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
