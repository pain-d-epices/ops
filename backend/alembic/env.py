"""Configuration Alembic : lit l'URL de connexion depuis .env, jamais depuis alembic.ini."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import parametres

# Import qui enregistre tous les modèles sur Base.metadata (indispensable à l'autogénération)
from app.modeles import Base  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", parametres().dsn.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def executer_migrations_hors_ligne() -> None:
    """Génère le SQL sans se connecter (mode --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def executer_migrations_en_ligne() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connexion:
        context.configure(
            connection=connexion,
            target_metadata=target_metadata,
            compare_type=True,          # détecte les changements de type de colonne
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    executer_migrations_hors_ligne()
else:
    executer_migrations_en_ligne()
