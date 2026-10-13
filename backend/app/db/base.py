"""Declarative base for ORM models. Models are added in Phase 1; Alembic reads this metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
