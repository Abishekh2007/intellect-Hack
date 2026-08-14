"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from config import Settings, get_settings
from db.seed import seed_database


@pytest.fixture(scope="session")
def settings():
    """A Settings with a temp seeded database, isolated from the repo DB."""
    tmp = Path(tempfile.mkdtemp(prefix="datapilot_test_"))
    db_path = tmp / "ecommerce.db"
    seed_database(db_path)
    settings = Settings(
        _env_file=None,
        db_path=db_path,
        llm_rpm=1000,  # tests must not be throttled
    )
    yield settings
    shutil.rmtree(tmp, ignore_errors=True)