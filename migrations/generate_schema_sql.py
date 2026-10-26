"""Regenerates migrations/001_initial_schema.sql from the SQLAlchemy models (PostgreSQL dialect).

Usage:  python migrations/generate_schema_sql.py > migrations/001_initial_schema.sql
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.models import Base  # noqa: E402

print("-- Quiz Master initial schema (PostgreSQL / Supabase). Safe to run once on an empty database.")
print("-- The app also creates missing tables automatically on startup (never drops anything).\n")
for table in Base.metadata.sorted_tables:
    stmt = str(CreateTable(table, if_not_exists=True).compile(dialect=postgresql.dialect())).strip()
    print(stmt + ";\n")
    for idx in sorted(table.indexes, key=lambda i: i.name):
        print(str(CreateIndex(idx, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    print()
