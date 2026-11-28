
from sqlmodel import Session, select

from src.db import engine
from src.models import Conversation, Message


def guardar_mensaje(thread_id: str, role: str, content: str):
    """Guarda un mensaje asociado a una conversación."""

    if role not in ("user", "assistant"):
        raise ValueError("El rol debe ser 'user' o 'assistant'")

    with Session(engine) as session:

        # Buscar si la conversación ya existe
        conversacion = session.get(Conversation, thread_id)

        # Si no existe, crearla
        if conversacion is None:
            conversacion = Conversation(thread_id=thread_id)
            session.add(conversacion)
            session.flush()

        # Crear el mensaje
        mensaje = Message(
            thread_id=thread_id,
            role=role,
            content=content
        )

        session.add(mensaje)
        session.commit()
        session.refresh(mensaje)

        return mensaje


def obtener_mensajes(thread_id: str):
    """Recupera los mensajes de una conversación en orden."""

    with Session(engine) as session:
        consulta = (
            select(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.created_at, Message.id)
        )

        mensajes = session.exec(consulta).all()

        return mensajes


def obtener_historial_api(thread_id: str) -> list[dict]:
    """
    Recupera los mensajes de PostgreSQL y los convierte
    al formato esperado por MessageOut.
    """

    mensajes = obtener_mensajes(thread_id)

    return [
        {
            "role": mensaje.role,
            "content": mensaje.content,
            "created_at": mensaje.created_at,
        }
        for mensaje in mensajes
    ]


def guardar_turno(
    thread_id: str,
    pregunta: str,
    respuesta: str
) -> None:
    """
    Guarda una pregunta y su respuesta en una sola transacción.
    Si ocurre un error, no se guarda ninguno de los dos mensajes.
    """

    if not thread_id or not thread_id.strip():
        raise ValueError("El thread_id no puede estar vacío")

    if not pregunta or not pregunta.strip():
        raise ValueError("La pregunta no puede estar vacía")

    if not respuesta or not respuesta.strip():
        raise ValueError("La respuesta no puede estar vacía")

    with Session(engine) as session:
        try:
            # Buscar la conversación
            conversacion = session.get(Conversation, thread_id)

            # Crear la conversación si todavía no existe
            if conversacion is None:
                session.add(Conversation(thread_id=thread_id))
                session.flush()

            # Preparar ambos mensajes
            mensaje_usuario = Message(
                thread_id=thread_id,
                role="user",
                content=pregunta
            )

            mensaje_asistente = Message(
                thread_id=thread_id,
                role="assistant",
                content=respuesta
            )

            # Añadir los dos mensajes
            session.add_all([
                mensaje_usuario,
                mensaje_asistente
            ])

            # Confirmar ambos mensajes a la vez
            session.commit()

        except Exception:
            session.rollback()
            raise
