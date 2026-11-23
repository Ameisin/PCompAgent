import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from src import models
from src import repository
from datetime import datetime

@pytest.fixture
def db_pruebas(monkeypatch):
    # Crear una base de datos temporal en memoria
    engine_pruebas = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    SQLModel.metadata.create_all(engine_pruebas)

    # Sustituir la conexión real por la de pruebas
    monkeypatch.setattr(repository, "engine", engine_pruebas)

    yield engine_pruebas

    engine_pruebas.dispose()


def test_guardar_y_recuperar_mensajes(db_pruebas):
    repository.guardar_mensaje("thread-001", "user", "Hola")
    repository.guardar_mensaje("thread-001", "assistant", "¡Hola!")

    mensajes = repository.obtener_mensajes("thread-001")

    assert len(mensajes) == 2
    assert mensajes[0].role == "user"
    assert mensajes[0].content == "Hola"
    assert mensajes[1].role == "assistant"
    assert mensajes[1].content == "¡Hola!"


def test_conversaciones_independientes(db_pruebas):
    repository.guardar_mensaje("thread-001", "user", "Mensaje A")
    repository.guardar_mensaje("thread-002", "user", "Mensaje B")

    mensajes_1 = repository.obtener_mensajes("thread-001")
    mensajes_2 = repository.obtener_mensajes("thread-002")

    assert len(mensajes_1) == 1
    assert len(mensajes_2) == 1
    assert mensajes_1[0].content == "Mensaje A"
    assert mensajes_2[0].content == "Mensaje B"
    
def test_guardar_mensaje_rechaza_rol_invalido():
    with pytest.raises(ValueError):
        repository.guardar_mensaje(
            thread_id="prueba-test",
            role="administrador",
            content="Hola"
        )


def test_obtener_historial_api(db_pruebas):
    repository.guardar_mensaje(
        "thread-api",
        "user",
        "Quiero montar un PC gaming"
    )

    repository.guardar_mensaje(
        "thread-api",
        "assistant",
        "¿Cuál es tu presupuesto?"
    )

    historial = repository.obtener_historial_api("thread-api")

    assert len(historial) == 2

    assert set(historial[0].keys()) == {
        "role",
        "content",
        "created_at"
    }

    assert historial[0]["role"] == "user"
    assert historial[0]["content"] == "Quiero montar un PC gaming"

    assert historial[1]["role"] == "assistant"
    assert historial[1]["content"] == "¿Cuál es tu presupuesto?"

    assert isinstance(historial[0]["created_at"], datetime)
