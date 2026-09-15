import random
import time


def response(question: str) -> dict:
    """ # 1. Retrieval
    chunks = retrieve(question)

    # 2. Generación
    response, abstencion = generate(question, chunks)

    return {
        "respuesta": response,
        "chunks": chunks,
        "k": TOP_K,
        "num_chunks": len(chunks),
        "modelo": MODEL_NAME,
        "tiempo_ms": elapsed_ms,
        "abstencion": abstencion
    } """

    """
    Mock de la función responder() para probar la UI sin RAG real.
    """

    start = time.time()

    # Simular chunks recuperados
    fake_chunks = [
        {
            "texto": "La placa base B550 soporta procesadores AMD Ryzen de 3ª y 5ª generación.",
            "source": "compatibilidad_placas.pdf"
        },
        {
            "texto": "La memoria RAM DDR4 es compatible con la mayoría de placas B550.",
            "source": "guia_ram.txt"
        }
    ]

    # Simular respuesta generada
    respuesta = (
        "Sí, en principio estos componentes son compatibles. "
        "La placa B550 admite CPUs Ryzen y RAM DDR4, según los documentos del corpus."
    )

    # Simular abstención aleatoria para probar la UI
    abstencion = random.choice([False, False, False, True])

    if abstencion:
        respuesta = (
            "No tengo suficiente información en los documentos para responder con seguridad."
        )

    elapsed_ms = int((time.time() - start) * 1000)

    return {
        "respuesta": respuesta,
        "chunks": fake_chunks,
        "k": 3,
        "num_chunks": len(fake_chunks),
        "modelo": "mock-model-v0",
        "tiempo_ms": elapsed_ms,
        "abstencion": abstencion
    }