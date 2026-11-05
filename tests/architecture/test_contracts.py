import subprocess
import sys
from pathlib import Path

from importlinter.cli import lint_imports

ROOT = Path(__file__).resolve().parents[2]


def test_import_contracts_hold(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert lint_imports(config_filename=str(ROOT / "pyproject.toml"), no_cache=True) == 0


def test_importing_the_core_does_not_load_web_or_db_libraries():
    script = (
        "import sys, qnuchat.core.pipeline, qnuchat.adapters.runtime\n"
        "banned = ('fastapi', 'starlette', 'sqlalchemy', 'psycopg')\n"
        "print(','.join(sorted(m for m in banned if m in sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""
