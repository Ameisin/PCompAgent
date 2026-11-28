
from uuid import uuid4

from src.repository import guardar_turno, obtener_historial_api


def test_conversaciones_independientes():
    thread_1 = f"test-hilo-1-{uuid4()}"
    thread_2 = f"test-hilo-2-{uuid4()}"

    guardar_turno(
        thread_id=thread_1,
        pregunta="Quiero un PC gaming",
        respuesta="¿Cuál es tu presupuesto?"
    )

    guardar_turno(
        thread_id=thread_2,
        pregunta="Quiero un PC para estudiar",
        respuesta="¿Qué programas necesitas?"
    )

    historial_1 = obtener_historial_api(thread_1)
    historial_2 = obtener_historial_api(thread_2)

    assert len(historial_1) == 2
    assert len(historial_2) == 2

    assert historial_1[0]["content"] == "Quiero un PC gaming"
    assert historial_1[1]["content"] == "¿Cuál es tu presupuesto?"

    assert historial_2[0]["content"] == "Quiero un PC para estudiar"
    assert historial_2[1]["content"] == "¿Qué programas necesitas?"

    print("OK: los dos thread_id mantienen historiales independientes")
    print("Thread 1:", thread_1)
    print("Thread 2:", thread_2)


if __name__ == "__main__":
    test_conversaciones_independientes()
