"""Alembic environment. The database URL always comes from settings (DATABASE_URL)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables owned by PostGIS / extensions — never touch them in migrations.
EXTENSION_TABLES = {"spatial_ref_sys", "geometry_columns", "geography_columns"}


# Columns managed by raw SQL (PostGIS geometry, full-text tsvector) — not mapped in the ORM.
RAW_SQL_COLUMNS = {"geom", "tsv"}
RAW_SQL_INDEXES = {"ix_regions_geom", "ix_districts_geom", "ix_rag_chunks_tsv"}


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
    if type_ == "table" and name in EXTENSION_TABLES:
        return False
    if type_ == "index" and name in RAW_SQL_INDEXES:
        return False
    return not (type_ == "column" and name in RAW_SQL_COLUMNS)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
