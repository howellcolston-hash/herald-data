"""Open the warehouse in DuckDB with one view per table.

    python -m herald.db                      an interactive-free check: prints the row count of every view
    from herald.db import connect; con = connect(); con.sql("SELECT ... FROM lines").show()

Views: lines, lines_current (one version per record), canadabuys_tenders, canadabuys_awards, canadabuys_contracts,
toronto_solicitations, toronto_awards. Each table view holds every stored version of every row (append-only); use
lines_current, or the QUALIFY clause in it, for the newest version of each record.
"""

from __future__ import annotations

import duckdb

from collectors import common
from herald import store

TABLES = [("canadabuys", "tenders"), ("canadabuys", "awards"), ("canadabuys", "contracts"),
          ("toronto", "solicitations"), ("toronto", "awards")]


def connect(database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database)
    for source, table in TABLES:
        files = store.parquet_files(store.table_root(source, table))
        if files:
            con.execute(f"CREATE OR REPLACE VIEW {source}_{table} AS "
                        f"SELECT * FROM read_parquet({store.sql_list(files)}, union_by_name=true)")
    lines = store.parquet_files(common.data_dir() / "lines")
    if lines:
        con.execute(f"CREATE OR REPLACE VIEW lines AS SELECT * FROM read_parquet({store.sql_list(lines)}, union_by_name=true)")
        con.execute("""CREATE OR REPLACE VIEW lines_current AS SELECT * FROM lines
                       QUALIFY row_number() OVER (PARTITION BY source, record_type, source_id, amendment
                                                  ORDER BY first_seen DESC, source_file DESC, row_hash) = 1""")
    return con


def main() -> int:
    con = connect()
    for (name,) in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal ORDER BY 1").fetchall():
        print(f"{name:28} {con.execute(f'SELECT count(*) FROM {name}').fetchone()[0]:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
