"""Shared pytest fixtures for phdb-plugin-example.

Spins up a fresh, migrated phdb SQLite DB per test using the
``MigrationRunner`` from the installed phdb package. Mirrors the
fixture shape in phdb's own ``tests/conftest.py`` so the example is
copy-pasteable for new plugin authors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phdb.db import connect
from phdb.migrations.runner import MigrationRunner

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """Return a path to a freshly created + fully migrated phdb DB."""
    db_path = tmp_path / "test.db"
    with connect(db_path, create=True) as conn:
        MigrationRunner(conn).apply_pending()
    return db_path


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the bundled JSON fixture directory."""
    return FIXTURES_DIR
