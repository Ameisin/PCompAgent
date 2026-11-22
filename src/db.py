
import os

from dotenv import load_dotenv
from sqlmodel import SQLModel, Session, create_engine

# Cargar las variables del archivo .env
load_dotenv()

# Obtener la conexión a PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("No se ha encontrado DATABASE_URL en el archivo .env")

# Crear el motor de conexión
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True
)


def get_session():
    """Proporciona una sesión para consultar la base de datos."""
    with Session(engine) as session:
        yield session


def create_db_and_tables():
    from src import models
    SQLModel.metadata.create_all(engine)