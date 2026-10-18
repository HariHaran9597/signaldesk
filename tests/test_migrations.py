from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from backend.db import Base, Item, make_engine
from backend.migrate import main as migrate


def test_migrate_baselines_complete_legacy_schema_and_preserves_rows(tmp_path, monkeypatch):
    database = tmp_path / "legacy.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)

    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Item(id="existing", source_id="test", topic="agents", title="Existing", url="https://example.com/item", excerpt="kept", content_hash="hash"))
        session.commit()
    engine.dispose()

    migrate()
    migrate()

    engine = make_engine(url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert inspector.get_table_names()
        assert connection.scalar(select(Item.id)) == "existing"
        assert connection.exec_driver_sql("select version_num from alembic_version").scalar_one() == "ca35722bd5ff"
    engine.dispose()
