
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database.base import Base
from app.models import Dataset, QueryHistory, User


config = context.config

# Use the actual database URL from the environment.
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("%", "%%"),
)

# Configure Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy metadata used by Alembic autogeneration.
target_metadata = Base.metadata

# Runtime-generated dataset tables must not be managed by Alembic.
DYNAMIC_DATASET_TABLE_PATTERN = re.compile(r"^dataset_[1-9]\d*$")


def include_object(object, name, type_, reflected, compare_to):
    """
    Ignore dynamically generated dataset tables during autogeneration.

    Permanent application tables, such as datasets, query_history,
    and users, remain managed by Alembic.
    """
    if type_ == "table" and reflected:
        if DYNAMIC_DATASET_TABLE_PATTERN.fullmatch(name or ""):
            return False

    return True


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live database connection."""

    connectable = engine_from_config(
        config.get_section(
            config.config_ini_section,
            {},
        ),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()