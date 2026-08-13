"""Alembic environment for the customer database.

Target metadata is `customer.persistence.base.customer_metadata`, populated by
importing every model module. The URL comes from CUSTOMER_DATABASE_URL only -
never from alembic.ini - so that no connection string lives in the repository.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Registers all customer tables on the shared metadata. Required import.
import customer.persistence.models  # noqa: F401
from customer.persistence.base import customer_metadata
from customer.persistence.session import customer_database_url

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers must stay False. Migrations run in-process (the
    # test fixtures call command.upgrade), and the default True would disable
    # every logger already configured by the operational runtime - including the
    # genie.* structured loggers that owner-review failure events and the
    # KeeSuri job diagnostics depend on.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = customer_metadata


def _database_url() -> str:
    """Resolve the URL, raising if unset (never silently default)."""
    return customer_database_url()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations in a transaction."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
