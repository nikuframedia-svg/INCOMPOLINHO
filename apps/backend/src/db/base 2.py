# Database base configuration
# Conforme SP-BE-02

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# Create engine
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # Verificar conexão antes de usar
    echo=settings.debug,  # Log SQL queries em debug
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency para obter sessão de DB"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
