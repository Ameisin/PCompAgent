"""Generación de respuestas con Gemini """

from google import genai

from config import GEMINI_MODEL, GENERATION_TEMPERATURE
from gemini_auto import configurar_gemini_api_key


def generar_respuesta(prompt: str) -> str:
    """Envía el prompt a Gemini y devuelve el texto de la respuesta."""
    configurar_gemini_api_key()
    client = genai.Client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"temperature": GENERATION_TEMPERATURE},
    )
    return (response.text or "").strip()