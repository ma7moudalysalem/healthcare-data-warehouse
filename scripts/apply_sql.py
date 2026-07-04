"""Apply a .sql file to Azure SQL Database, splitting on `GO` batch separators.

Connection comes from env vars:
    HCDW_SQL_SERVER   e.g. hcdw-sqlne-44ba4327.database.windows.net
    HCDW_SQL_DB       e.g. healthcare
    HCDW_SQL_USER     e.g. hcdwadmin
    HCDW_SQL_PASSWORD

Usage:
    python scripts/apply_sql.py sql/ddl/azuresql/warehouse_azuresql.sql
"""
from __future__ import annotations

import os
import re
import sys

import pyodbc


def connect() -> pyodbc.Connection:
    cs = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['HCDW_SQL_SERVER']};"
        f"DATABASE={os.environ['HCDW_SQL_DB']};"
        f"UID={os.environ['HCDW_SQL_USER']};"
        f"PWD={os.environ['HCDW_SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60"
    )
    return pyodbc.connect(cs, autocommit=True)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: apply_sql.py <file.sql>", file=sys.stderr)
        return 2
    path = argv[0]
    with open(path, encoding="utf-8") as fh:
        script = fh.read()
    batches = [b for b in re.split(r"(?im)^\s*GO\s*$", script) if b.strip()]
    cn = connect()
    cur = cn.cursor()
    for i, batch in enumerate(batches, 1):
        try:
            cur.execute(batch)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! batch {i} failed: {str(exc)[:300]}", file=sys.stderr)
            print(batch[:400], file=sys.stderr)
            cn.close()
            return 1
    cn.close()
    print(f"applied {len(batches)} batches from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
