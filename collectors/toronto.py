"""City of Toronto solicitations and awarded contracts (Toronto Open Data, Open Government Licence - Toronto).

    python -m collectors.toronto                  daily run: rows not stored yet go to data/toronto/<table>/daily/<today>.parquet
    python -m collectors.toronto --backfill       rebuild <fy>/base.parquet from the current files (the files carry the
                                                  whole history the City publishes)
    python -m collectors.toronto --date YYYY-MM-DD   redo one day's increment
    --table solicitations|awards (repeatable), --files DIR (read all-solicitations.csv / awarded-contracts.csv from DIR)

Datasets: tobids-all-open-solicitations and tobids-awarded-contracts on ckan0.cf.opendata.inter.prod-toronto.ca.
The awarded-contracts file repeats each document's whole Award list (JSON) on every row; it is stored as one row per
(document, awarded supplier, amount, date). Card: catalog/toronto.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

import duckdb

from collectors import common
from herald import schema, store

COLLECTOR = "toronto"
TABLES = ("solicitations", "awards")
URLS = {
    "solicitations": ("all-solicitations.csv", "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
                      "434c2d91-1736-432a-a69f-d5b3890f239f/resource/5e88e4e1-5df0-4733-bd97-fa06a89e69ca/download/"
                      "all-solicitations.csv"),
    "awards": ("awarded-contracts.csv", "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
               "f78fe449-53f4-4962-9ec8-8f7eeece1072/resource/81be799c-0fae-4a29-9458-0dc3ef471ca5/download/"
               "awarded-contracts.csv"),
}
ORDER_BY = {"solicitations": "document_number, row_hash", "awards": "document_number, supplier, row_hash"}
csv.field_size_limit(sys.maxsize)


def award_records(path: Path, notes: list[str]) -> Iterator[dict]:
    """One record per award inside each row's Award JSON list, deduplicated across the repeated rows."""
    seen = set()
    bad = 0
    for rec in store.csv_records(path, schema.TORONTO["awards"][:9], notes):
        try:
            awards = json.loads(rec.get("Award") or "[]") or []
        except json.JSONDecodeError:
            bad += 1
            awards = []
        for a in awards:
            if not isinstance(a, dict):
                continue
            key = (rec.get("Document Number"), a.get("Successful_Bidder"), a.get("Award_Amount"), a.get("Date_Awarded"))
            if key in seen:
                continue
            seen.add(key)
            out = dict(rec)
            out.update({k: ("" if v is None else str(v)) for k, v in a.items()})
            yield out
    if bad:
        notes.append(f"{path.name}: {bad} rows with an unreadable Award list")


def stage_table(table: str, files_dir: Path | None, workdir: Path, run_date, ctx: dict) -> list[Path]:
    name, url = URLS[table]
    path = (files_dir / name) if files_dir else common.http_download(url, workdir / name)
    spec = schema.TORONTO[table]
    records = award_records(path, ctx["notes"]) if table == "awards" else store.csv_records(path, spec, ctx["notes"])
    stats, bad = Counter(), Counter()
    rows = store.typed_rows(records, spec, schema.TORONTO_PARTITION_DATE[table], name, run_date, stats, bad)
    staged = store.stage(rows, spec, workdir / "staging" / f"{table}.parquet")
    ctx["counts"].setdefault("source_rows", {})[name] = stats["read"]
    if bad:
        ctx["notes"].append(f"{name}: unparseable values set to NULL: " + ", ".join(f"{k} {v}" for k, v in bad.most_common()))
    return [staged]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.toronto", description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--backfill", action="store_true")
    mode.add_argument("--date", type=common.parse_date)
    ap.add_argument("--table", action="append", choices=TABLES)
    ap.add_argument("--files", type=Path)
    args = ap.parse_args(argv)
    tables = args.table or list(TABLES)
    run_date = common.today_utc()
    day = args.date or run_date
    workdir = common.cache_dir() / COLLECTOR / day.isoformat()
    con = duckdb.connect()
    with common.run(COLLECTOR, {"backfill": args.backfill, "date": day.isoformat(), "tables": tables}) as ctx:
        for table in tables:
            root = store.table_root(COLLECTOR, table)
            try:
                staged = stage_table(table, args.files, workdir, run_date, ctx)
            except common.FetchError as e:
                ctx["notes"].append(f"{table}: not fetched ({e})")
                ctx["status"] = "partial"
                continue
            if args.backfill:
                written = store.write_base(con, root, staged, None, ORDER_BY[table])
                n = sum(written.values())
                ctx["periods"] += [f"{table}:{fy}" for fy in sorted(written)]
            else:
                n = store.write_daily(con, root, staged, day, ORDER_BY[table])
                ctx["periods"].append(f"{table}:{day.isoformat()}")
            ctx["counts"].setdefault("written", {})[table] = n
            ctx["counts"].setdefault("stored_rows", {})[table] = store.count_rows(con, root)
            ctx["rows"] += n
            ctx["notes"].append(f"{table}: {n} rows written")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
