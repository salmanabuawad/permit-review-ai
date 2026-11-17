import os
import sys
import tempfile
from pathlib import Path

# isolated DB + storage for the whole test session — must be set before importing app.*
_tmp = Path(tempfile.mkdtemp(prefix="bbp_test_"))
# BBP_TEST_DATABASE_URL lets the same suite run on PostgreSQL (e.g. an embedded pgserver instance)
os.environ["BBP_DATABASE_URL"] = os.environ.get("BBP_TEST_DATABASE_URL") or f"sqlite:///{(_tmp / 'test.sqlite3').as_posix()}"
os.environ["BBP_STORAGE_DIR"] = str(_tmp / "storage")
os.environ["BBP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "fixtures" / "demo"


@pytest.fixture(scope="session", autouse=True)
def _fixtures():
    if not (FIX / "case1_extension_exceeds.dxf").exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_fixtures.py")], check=True)
    yield
