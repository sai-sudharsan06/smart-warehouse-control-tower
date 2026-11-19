import subprocess
import sys
from pathlib import Path

from warehouse import database
from warehouse.inventory import check_stock_against_ledger
from warehouse.orders import list_orders

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo_data.py"


def test_two_week_simulation_keeps_the_ledger_consistent(tmp_path, monkeypatch):
    output = tmp_path / "demo.db"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--weeks", "2", "--seed", "1", "--output", str(output)],
        capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    monkeypatch.setattr(database, "DB_PATH", output)
    assert check_stock_against_ledger() == []
    assert len(list_orders(status="Shipped")) > 0


def test_script_refuses_to_overwrite_the_real_database(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(tmp_path / "warehouse.db")],
        capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr
