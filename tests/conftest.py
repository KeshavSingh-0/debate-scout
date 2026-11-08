import os
import tempfile

_tmp_dir = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_dir}/test.db")
os.environ.setdefault("UPLOAD_DIR", f"{_tmp_dir}/uploads")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    from app.db import init_db

    init_db()
