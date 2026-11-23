"""CanadaBuys tender notices, award notices and contract history (open.canada.ca, Open Government Licence - Canada).

    python -m collectors.canadabuys                       daily run: the new-notice and open-notice files and the
                                                          current fiscal year's files; rows not stored yet go to
                                                          data/canadabuys/<table>/daily/<today>.parquet
    python -m collectors.canadabuys --full                daily run that also reads the "complete" files (weekly)
    python -m collectors.canadabuys --backfill            rebuild <fy>/base.parquet for every fiscal year from the
                                                          legacy and complete files
    python -m collectors.canadabuys --backfill --fy 2015-2016 [--fy ...]   only those fiscal years
    python -m collectors.canadabuys --backfill --start 2015-04-01 --end 2017-03-31   the fiscal years in a range
    python -m collectors.canadabuys --date 2026-11-23     redo one day's increment (same as the daily run, dated)
    --table tenders|awards|contracts (repeatable)         limit any of the above to some tables
    --files DIR                                           read the published files from DIR instead of downloading

Re-running a period rewrites the same files (base for a fiscal year, daily for a day). A daily run in which one file
can't be fetched is logged as partial; one in which no file of a table can be fetched is logged as failed and exits 1,
so the workflow shows red. Packages: tender notices
6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2, award notices a1acb126-9ce8-40a9-b889-5da2b1dd20cb, contract history
4fe645a1-ffcd-40c1-9385-2c771be956a4. Card: catalog/canadabuys_*.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
from collections import Counter
from pathlib import Path

import duckdb

from collectors import common
from herald import schema, store

COLLECTOR = "canadabuys"
BASE_URL = "https://canadabuys.canada.ca/opendata/pub/"
TABLES = ("tenders", "awards", "contracts")
ORDER_BY = "reference_number, amendment_number, row_hash"

# Published files per table. {fy} is a fiscal year like 2026-2027.
BACKFILL_FILES = {
    "tenders": ["2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv",
                "tenderNoticeComplete-avisAppelOffresComplet.csv"],
    "awards": ["2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv",
               "awardNoticeComplete-avisAttributionComplet.csv"],
    "contracts": ["2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv",
                  "contractHistoryComplete-contratsOctroyesComplet.csv"],
}
DAILY_FILES = {
    "tenders": ["newTenderNotice-nouvelAvisAppelOffres.csv", "openTenderNotice-ouvertAvisAppelOffres.csv",
                "{fy}-TenderNotice-AvisAppelOffres.csv"],
    "awards": ["{fy}-awardNotice-avisAttribution.csv"],
    "contracts": ["{fy}-contractHistory-contratsOctroyes.csv"],
}
FULL_FILES = {t: [BACKFILL_FILES[t][1]] for t in TABLES}   # the "complete" files, read weekly by --full


def daily_names(table: str, day: dt.date, full: bool) -> list[str]:
    fys = [common.fiscal_year(day)]
    if day.month in (4, 5):        # the new fiscal year's file can lag; keep reading last year's until June
        fys.append(common.fiscal_year(day - dt.timedelta(days=62)))
    names = []
    for pattern in DAILY_FILES[table]:
        names += [pattern.format(fy=fy) for fy in fys] if "{fy}" in pattern else [pattern]
    if full:
        names += FULL_FILES[table]
    return list(dict.fromkeys(names))


def fetch(name: str, files_dir: Path | None, workdir: Path) -> Path:
    if files_dir:
        p = files_dir / name
        if not p.exists():
            raise common.FetchError(f"{p} not found")
        return p
    return common.http_download(BASE_URL + name, workdir / name)


def stage_files(table: str, names: list[str], files_dir: Path | None, workdir: Path, run_date: dt.date,
                ctx: dict, required: bool) -> list[Path]:
    """Download and stage each published file. A missing file fails the run when `required`, else is noted."""
    spec = schema.CANADABUYS[table]
    staged = []
    for name in names:
        try:
            path = fetch(name, files_dir, workdir)
        except common.FetchError as e:
            if required:
                raise
            ctx["notes"].append(f"{table}: {name} not fetched ({e})")
            ctx["status"] = "partial"
            continue
        stats, bad = Counter(), Counter()
        rows = store.typed_rows(store.csv_records(path, spec, ctx["notes"]), spec,
                                schema.CANADABUYS_PARTITION_DATE[table], name, run_date, stats, bad)
        staged.append(store.stage(rows, spec, workdir / "staging" / table / f"{Path(name).stem}.parquet"))
        ctx["counts"].setdefault("source_rows", {})[name] = stats["read"]
        if bad:
            ctx["notes"].append(f"{name}: unparseable values set to NULL: " +
                                ", ".join(f"{k} {v}" for k, v in bad.most_common()))
        if not files_dir and path.parent == workdir:
            path.unlink()   # keep the runner's disk small: the staged copy is all we need
    return staged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.canadabuys", description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--backfill", action="store_true", help="rebuild fiscal-year base files from the full history")
    mode.add_argument("--date", type=common.parse_date, help="redo the daily increment for this date")
    ap.add_argument("--full", action="store_true", help="daily run that also reads the complete files")
    ap.add_argument("--fy", action="append", help="with --backfill: a fiscal year like 2015-2016 (repeatable)")
    ap.add_argument("--start", type=common.parse_date, help="with --backfill: first date of a range of fiscal years")
    ap.add_argument("--end", type=common.parse_date, help="with --backfill: last date of the range")
    ap.add_argument("--table", action="append", choices=TABLES, help="limit to these tables (repeatable)")
    ap.add_argument("--files", type=Path, help="read published files from this directory instead of downloading")
    args = ap.parse_args(argv)

    tables = args.table or list(TABLES)
    fys = list(args.fy or [])
    if args.start or args.end:
        if not (args.start and args.end and args.backfill):
            common.die("--start and --end go together, with --backfill")
        y = int(common.fiscal_year(args.start)[:4])
        while y <= int(common.fiscal_year(args.end)[:4]):
            fys.append(f"{y}-{y + 1}")
            y += 1
    run_date = common.today_utc()
    day = args.date or run_date
    params = {"backfill": args.backfill, "full": args.full, "date": day.isoformat(), "fy": fys, "tables": tables}
    workdir = common.cache_dir() / COLLECTOR / day.isoformat()
    con = duckdb.connect()
    failed = False

    with common.run(COLLECTOR, params) as ctx:
        for table in tables:
            root = store.table_root(COLLECTOR, table)
            if args.backfill:
                staged = stage_files(table, BACKFILL_FILES[table], args.files, workdir, run_date, ctx, required=True)
                written = store.write_base(con, root, staged, fys or None, ORDER_BY)
                ctx["counts"].setdefault("written", {})[table] = written
                ctx["rows"] += sum(written.values())
                ctx["periods"] += [f"{table}:{fy}" for fy in sorted(written)]
                distinct = con.execute(
                    f"SELECT count(DISTINCT row_hash) FROM read_parquet({store.sql_list(staged)}, union_by_name=true)"
                    + (f" WHERE fiscal_year IN ({', '.join(repr(f) for f in fys)})" if fys else "")).fetchone()[0]
                ctx["counts"].setdefault("distinct_source_rows", {})[table] = distinct
                ctx["notes"].append(f"{table}: {sum(written.values())} rows in {len(written)} fiscal years "
                                    f"({distinct} distinct rows in the source files)")
            else:
                names = daily_names(table, day, args.full)
                staged = stage_files(table, names, args.files, workdir, run_date, ctx, required=False)
                if not staged:
                    ctx["notes"].append(f"{table}: no file could be read")
                    ctx["status"] = "failed"
                    failed = True
                    continue
                n = store.write_daily(con, root, staged, day, ORDER_BY)
                ctx["counts"].setdefault("written", {})[table] = n
                ctx["rows"] += n
                ctx["periods"].append(f"{table}:{day.isoformat()}")
                ctx["notes"].append(f"{table}: {n} new or changed rows from {len(staged)} files")
            ctx["counts"].setdefault("stored_rows", {})[table] = store.count_rows(con, root)
        if failed:
            ctx["status"] = "failed"      # a later table's partial note must not hide a table that got nothing
    shutil.rmtree(workdir, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
