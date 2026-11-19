import pytest

from warehouse import database


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Give each test its own empty, temporary database."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test_warehouse.db")
    database.create_tables()