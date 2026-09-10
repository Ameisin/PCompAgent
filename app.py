import streamlit as st
from src.responder import responder

st.set_page_config(page_title="RAG PC Builder", page_icon="🖥️")

st.title("🖥️ Asistente RAG — Montaje y compatibilidad de PC")

# Inicializar historial
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada del usuario
pregunta = st.chat_input("Pregunta sobre componentes o compatibilidad...")

if pregunta:
    # Mostrar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": pregunta})
    with st.chat_message("user"):
        st.markdown(pregunta)

    # Llamar a tu API interna
    resultado = responder(pregunta)

    respuesta = resultado["respuesta"]
    chunks = resultado["chunks"]
    modelo = resultado["modelo"]
    k = resultado["k"]
    num_chunks = resultado["num_chunks"]
    tiempo_ms = resultado["tiempo_ms"]
    abstencion = resultado.get("abstencion", False)

    # Mostrar respuesta del agente
    with st.chat_message("assistant"):
        st.markdown(respuesta)

        # Mostrar contexto recuperado
        st.subheader("🔍 Chunks recuperados")
        for ch in chunks:
            st.markdown(f"""
            **Fuente:** `{ch['source']}`  
            ```
            {ch['texto']}
            ```
            """)

        # Métricas
        st.subheader("📊 Métricas")
        st.markdown(f"""
        - **Modelo:** {modelo}  
        - **Top‑K:** {k}  
        - **Chunks usados:** {num_chunks}  
        - **Tiempo:** {tiempo_ms} ms  
        - **Abstención:** {"Sí" if abstencion else "No"}  
        """)

    # Guardar respuesta en historial
    st.session_state.messages.append({"role": "assistant", "content": respuesta})
