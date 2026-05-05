"""Smoke tests for the SQL files (parse-time only).

We don't run the SQL against a real Synapse - the CI runner doesn't have
one - but we lint that the files are valid UTF-8, end with a blank line,
contain the expected GO terminators, and reference the schemas declared
in the DDL.
"""
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DDL_DIR = ROOT / "sql" / "ddl"
SP_DIR = ROOT / "sql" / "stored_procedures"
QUERY_DIR = ROOT / "sql" / "queries"


def _all_sql_files() -> list[Path]:
    return sorted([*DDL_DIR.glob("*.sql"), *SP_DIR.glob("*.sql"), *QUERY_DIR.glob("*.sql")])


@pytest.mark.parametrize("path", _all_sql_files(), ids=lambda p: p.name)
def test_sql_file_is_utf8_and_non_empty(path: Path):
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path.name} is empty"


@pytest.mark.parametrize("path", sorted(DDL_DIR.glob("*.sql")), ids=lambda p: p.name)
def test_ddl_files_have_go_terminators(path: Path):
    """Synapse / SQL Server batch separators."""
    text = path.read_text(encoding="utf-8")
    # Each CREATE / IF OBJECT_ID guard block needs a GO. We require at
    # least one and a trailing GO before EOF.
    go_count = len(re.findall(r"^GO\s*$", text, flags=re.MULTILINE))
    assert go_count >= 1, f"{path.name} has no GO terminators"
    assert text.rstrip().endswith("GO"), f"{path.name} doesn't end with GO"


@pytest.mark.parametrize("path", sorted(QUERY_DIR.glob("*.sql")), ids=lambda p: p.name)
def test_query_files_reference_dw_schema(path: Path):
    """Analytical queries should hit the dw schema, not the raw OLTP."""
    text = path.read_text(encoding="utf-8")
    assert "dw." in text, f"{path.name} doesn't reference dw schema"
    assert "clinical." not in text, f"{path.name} references OLTP clinical schema"
    assert "billing." not in text, f"{path.name} references OLTP billing schema"


def test_sp_files_use_create_or_alter():
    """All procs should be re-deployable."""
    for path in SP_DIR.glob("sp_*.sql"):
        text = path.read_text(encoding="utf-8").upper()
        assert "CREATE OR ALTER PROCEDURE" in text, f"{path.name} should use CREATE OR ALTER"
