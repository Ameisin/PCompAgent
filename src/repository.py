
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
