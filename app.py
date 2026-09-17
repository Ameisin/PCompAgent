import pandas as pd
import streamlit as st
import config as cfg

from logic import responder

st.set_page_config(page_title="RAG PC Builder", page_icon="🖥️")

st.sidebar.title("⚙️ Configuración")

model_choice = st.sidebar.selectbox(
    "Modelo de generación",
    ["gemini-1.5-flash", "gemini-1.5-pro"],
    index=0
)

top_k = st.sidebar.slider("Top‑K (chunks recuperados)", 1, 10, 3)

debug_mode = st.sidebar.checkbox("Modo debug", value=False)

if st.sidebar.button("🧹 Limpiar historial"):
    st.session_state.messages = []

st.sidebar.markdown("---")
st.sidebar.markdown("**RAG PC Builder — Bootcamp The Bridge**")

st.title("🖥️ Asistente RAG — Montaje y compatibilidad de PC")

# Inicializar historial
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada del usuario
question = st.chat_input("Pregunta sobre componentes o compatibilidad...")

if question:
    # Mostrar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Llamar a tu API interna
    result = responder(question, top_k)

    answer = result["respuesta"]
    chunks = result["chunks"]
    model = cfg.nombre_modelo_embedding()
    k = top_k
    num_chunks = len(chunks)
    time_ms = result["tiempo_ms"]
    
    # Mostrar respuesta del agente
    with st.chat_message("assistant"):
        st.markdown(answer)

        # Mostrar contexto recuperado
        st.subheader("🔍 Chunks recuperados:")
        for i, chunk in enumerate(chunks, start=1):
            source = chunk.get("metadata", {}).get("source", "?")
            dist = chunk.get("distance")
            dist_txt = f"{dist:.4f}" if dist is not None else "n/a"
            st.markdown(f"**Chunk #{i}** (source: {source}, distance: {dist_txt})")
            st.markdown(f"```\n{chunk['text']}\n```")

        st.subheader("Fuentes de información:")
        for fuente in result["fuentes"]:
            st.markdown(f"- {fuente}")

        # Métricas
        st.subheader("📊 Métricas")

        metricas = {
            "Modelo": [model],
            "Top‑K": [k],
            "Chunks usados": [num_chunks],
            "Tiempo (ms)": [time_ms]
        }

        df_metricas = pd.DataFrame(metricas)
        st.table(df_metricas)

    # Guardar respuesta en historial
    st.session_state.messages.append({"role": "assistant", "content": answer})
