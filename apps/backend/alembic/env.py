"""
Alembic Environment Configuration for JARV Backend
"""
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.models.base import Base

# Import all models here to ensure they are registered with Base.metadata
import app.models  # noqa: F401 - Import to register all models

# Alembic Config object
config = context.config


def process_revision_directives(context, revision, directives):
    """Process migration directives to handle circular dependencies"""
    if config.cmd_opts and config.cmd_opts.autogenerate:
        script = directives[0]
        if script.upgrade_ops:
            # Sort create_table operations using metadata's sorted_tables
            # which uses topological sort to handle dependencies
            from sqlalchemy import MetaData

            ops = script.upgrade_ops.ops
            create_ops = [op for op in ops if hasattr(op, 'table_name')]
            other_ops = [op for op in ops if op not in create_ops]

            # Use SQLAlchemy's sorted_tables for proper dependency ordering
            sorted_table_names = [t.name for t in Base.metadata.sorted_tables]

            # Sort create_ops based on sorted_table_names order
            def get_table_order(op):
                try:
                    return sorted_table_names.index(op.table_name)
                except ValueError:
                    # If not found, put at the end
                    return len(sorted_table_names)

            ops_sorted = sorted(create_ops, key=get_table_order)

            # Replace ops with sorted version
            script.upgrade_ops.ops = ops_sorted + other_ops

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata

# Set database URL from settings
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with the given connection"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode"""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = str(settings.DATABASE_URL).replace(
        "postgresql://", "postgresql+asyncpg://"
    )

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection
    with the context.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
