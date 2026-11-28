import os

import requests
import streamlit as st
from dotenv import load_dotenv

# Carga front/.env sin depender de desde dónde se ejecute Streamlit.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("API_KEY", "")
TIMEOUT_S = 330  # algo más que ASK_TIMEOUT_SECONDS del servicio

MENSAJES_ERROR = {
    401: "La API key no es correcta.",
    429: "Has hecho demasiadas peticiones. Espera un minuto.",
    503: "La API no tiene API_KEY configurada.",
    504: "El turno tardó demasiado y se cortó.",
}


def llamar(metodo: str, ruta: str, **kwargs) -> dict:
    """Llama a la API con la clave en query y traduce los errores a mensajes."""
    try:
        r = requests.request(
            metodo, BASE + ruta, params={"api_key": API_KEY}, timeout=TIMEOUT_S, **kwargs
        )
    except requests.RequestException as e:
        raise RuntimeError(f"No puedo conectar con la API en {BASE}.") from e
    if r.status_code >= 400:
        raise RuntimeError(MENSAJES_ERROR.get(r.status_code, f"Error {r.status_code} de la API."))
    return r.json()


def api_disponible() -> bool:
    try:
        return requests.get(BASE + "/health", timeout=5).status_code == 200
    except requests.RequestException:
        return False


def enviar_pregunta(pregunta: str) -> None:
    try:
        out = llamar("POST", "/ask", json={
            "pregunta": pregunta,
            "thread_id": st.session_state.thread_id,
            "auto_aprobar": False,  # así el plan se pausa y aprobamos desde el front
        })
    except RuntimeError as e:
        st.session_state.error = str(e)
        return
    st.session_state.thread_id = out["thread_id"]
    st.session_state.pendiente = out["pendiente_hitl"]
    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    st.session_state.mensajes.append({"role": "assistant", "content": out["respuesta"]})


def decidir(aprobado: bool) -> None:
    try:
        out = llamar("POST", "/approve", json={
            "thread_id": st.session_state.thread_id,
            "aprobado": aprobado,
        })
    except RuntimeError as e:
        st.session_state.error = str(e)
        return
    st.session_state.pendiente = out["pendiente_hitl"]
    st.session_state.mensajes.append({"role": "assistant", "content": out["respuesta"]})


# Estado de la sesión del navegador
st.session_state.setdefault("thread_id", None)
st.session_state.setdefault("pendiente", False)
st.session_state.setdefault("mensajes", [])
st.session_state.setdefault("error", None)

with st.sidebar:
    st.header("Conexión")
    if api_disponible():
        st.success("API disponible")
    else:
        st.error("API no disponible")
    st.caption(BASE)

    st.markdown("**Thread ID**")
    st.code(st.session_state.thread_id or "sin conversación")

    if st.button("🆕 Nueva conversación"):
        st.session_state.thread_id = None
        st.session_state.pendiente = False
        st.session_state.mensajes = []
        st.session_state.error = None

st.title("Asesor de PC")

pregunta = st.chat_input("Escribe tu pregunta")
if pregunta:
    enviar_pregunta(pregunta)

# TODO Parte 2: el historial debe venir de GET /threads/{id}/messages.
# Hasta entonces, se muestra lo de esta sesión del navegador.
for m in st.session_state.mensajes:
    with st.chat_message(m["role"]):
        st.write(m["content"])

err = st.session_state.pop("error", None)
if err:
    st.error(err)

if st.session_state.pendiente:
    st.info("Hay un plan pendiente de aprobación.")
    col1, col2 = st.columns(2)
    col1.button("✅ Aprobar", on_click=decidir, args=(True,), use_container_width=True)
    col2.button("❌ Rechazar", on_click=decidir, args=(False,), use_container_width=True)