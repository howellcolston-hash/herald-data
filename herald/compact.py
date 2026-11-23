"""Monthly compaction: fold the daily increment files of finished months into one file per fiscal year and month.

    python -m herald.compact                    fold every daily file dated before the first of this month
    python -m herald.compact --before 2026-11-01

data/<source>/<table>/daily/2026-10-*.parquet become data/<source>/<table>/<fy>/m-2026-10.parquet. Rows keep their
first_seen; nothing is dropped except exact duplicates of a row_hash. Run `python -m herald.lines` afterwards: it
builds the lines for the new monthly files and removes the lines of the folded daily files.
"""

from __future__ import annotations

import argparse
import datetime as dt

import duckdb

from collectors import common
from herald import store

ORDER_BY = {
    ("canadabuys", "tenders"): "reference_number, amendment_number, row_hash",
    ("canadabuys", "awards"): "reference_number, amendment_number, row_hash",
    ("canadabuys", "contracts"): "reference_number, amendment_number, row_hash",
    ("toronto", "solicitations"): "document_number, row_hash",
    ("toronto", "awards"): "document_number, supplier, row_hash",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m herald.compact", description=__doc__.split("\n\n")[0])
    ap.add_argument("--before", type=common.parse_date, help="fold daily files dated before this day")
    args = ap.parse_args(argv)
    today = common.today_utc()
    before = args.before or today.replace(day=1)
    con = duckdb.connect()
    with common.run("compact", {"before": before.isoformat()}) as ctx:
        for (source, table), order in ORDER_BY.items():
            root = store.table_root(source, table)
            if not (root / "daily").exists():
                continue
            moved = store.compact(con, root, before, order)
            for path, n in moved.items():
                ctx["rows"] += n
                ctx["periods"].append(path)
            if moved:
                ctx["notes"].append(f"{source}/{table}: {len(moved)} monthly files written")
        if not ctx["periods"]:
            ctx["notes"].append("nothing to fold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
