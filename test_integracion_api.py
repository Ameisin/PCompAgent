
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from api import app
from src.repository import obtener_historial_api


def agente_simulado(estado, pregunta, thread_id, max_turns):
    estado["respuesta"] = "Para gaming, empezaría por definir el presupuesto."
    estado["error"] = None
    estado["done"] = False
    estado["pendiente_hitl"] = False
    estado.setdefault("traza", []).append({
        "status": "ok",
        "mensaje": pregunta
    })
    return estado


def test_guardado_automatico():
    import os

    client = TestClient(app)
    thread_id = f"integracion-{uuid4()}"

    with patch("api.procesar_turno", side_effect=agente_simulado):
        respuesta = client.post(
            "/ask",
            params={"api_key": os.environ["API_KEY"]},
            json={
                "pregunta": "Quiero montar un PC gaming",
                "thread_id": thread_id,
                "auto_aprobar": False
            }
        )

    assert respuesta.status_code == 200, respuesta.text

    mensajes = obtener_historial_api(thread_id)

    assert len(mensajes) == 2
    assert mensajes[0]["role"] == "user"
    assert mensajes[0]["content"] == "Quiero montar un PC gaming"
    assert mensajes[1]["role"] == "assistant"
    assert mensajes[1]["content"] == "Para gaming, empezaría por definir el presupuesto."

    print("Integración FastAPI + PostgreSQL correcta")


if __name__ == "__main__":
    test_guardado_automatico()
