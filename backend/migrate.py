"""Apply database migrations, safely baselining a complete legacy schema."""
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import inspect

from .db import Base, make_engine

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL", "sqlite:///./data/signaldesk.db")
    engine = make_engine(url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            should_stamp = bool(tables and "alembic_version" not in tables)
            expected = set(Base.metadata.tables)
            mismatches = []
            if should_stamp:
                for table in sorted(expected):
                    if table not in tables:
                        mismatches.append(f"{table} (missing)")
                        continue
                    actual_columns = {column["name"] for column in inspector.get_columns(table)}
                    expected_columns = set(Base.metadata.tables[table].columns.keys())
                    if actual_columns != expected_columns:
                        mismatches.append(f"{table} (columns differ)")
        if mismatches:
            raise RuntimeError("Cannot baseline unversioned database safely: " + ", ".join(mismatches))
        if should_stamp:
            # Prior local previews used metadata.create_all. The initial revision
            # describes that same schema, so mark it without recreating user data.
            command.stamp(config, "head")
        command.upgrade(config, "head")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
