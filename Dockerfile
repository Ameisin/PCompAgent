# Imagen base oficial de Python (ligera). Usamos 3.14, la versión con la que
# hemos desarrollado y fijado las versiones de requirements.txt.
FROM python:3.14-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Los print y logs salen al momento en los logs de Render (sin buffer)
ENV PYTHONUNBUFFERED=1

# Primero solo requirements.txt: si las dependencias no cambian, Docker
# reutiliza esta capa y los siguientes builds son mucho más rápidos.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código de la API (api.py, schemas.py), el agente (src/, tools/), el RAG
# (módulos de la raíz), el corpus (data/), el índice ya construido (chroma/)
# y la imagen de la tool multimodal (assets/).
# .dockerignore deja fuera .env, .venv, .git y lo que no hace falta para servir.
COPY . .

# Puerto documentado (en local hay que publicarlo con -p al hacer run)
EXPOSE 8000

# Puerto 8000 por defecto; Render inyecta PORT y entonces se usa ese.
# Un solo proceso de uvicorn: el MemorySaver del grafo vive en su memoria.
CMD uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}
