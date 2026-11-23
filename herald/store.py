"""Append-only Parquet storage shared by every collector.

Layout of one table (data/<source>/<table>/):

    <fiscal year>/base.parquet         everything the backfill read for that fiscal year (base-1, base-2, ... if over the size cap)
    <fiscal year>/m-<YYYY-MM>.parquet   rows first seen in that month, written by the monthly compaction
    daily/<YYYY-MM-DD>.parquet          rows first seen that day, all fiscal years together, until compaction

A row is never changed or removed: when the source publishes a changed row (an amendment, a corrected value, a new
status) it gets a new row_hash and is stored beside the old one. Readers pick the version they need (herald/db.py).
No file goes over common.MAX_FILE_BYTES: a larger write is split into numbered parts.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from collectors import common
from herald.schema import arrow_schema

csv.field_size_limit(sys.maxsize)
BATCH_ROWS = 20_000
_FLOAT_JUNK = re.compile(r"[,$\s]")


def table_root(source: str, table: str) -> Path:
    return common.data_dir() / source / table


def parquet_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.parquet") if not p.name.startswith("."))


def sql_list(paths: Iterable[Path]) -> str:
    return "[" + ", ".join("'" + p.as_posix().replace("'", "''") + "'" for p in paths) + "]"


# --------------------------------------------------------------------------- parsing

def convert(value: str | None, kind: str, bad: Counter, column: str):
    """One published cell to its stored value (see herald/schema.py for the kinds)."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if kind == "str":
        return v
    if kind == "multi":
        parts = [p.strip().lstrip("*").strip() for p in v.replace("\r", "\n").split("\n")]
        parts = [p for p in parts if p]
        return "; ".join(parts) or None
    if kind == "date":
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError:
            bad[column] += 1
            return None
    if kind == "ts":
        try:
            return dt.datetime.fromisoformat(v[:19])
        except ValueError:
            try:
                return dt.datetime.combine(dt.date.fromisoformat(v[:10]), dt.time())
            except ValueError:
                bad[column] += 1
                return None
    if kind == "float":
        try:
            return float(_FLOAT_JUNK.sub("", v))
        except ValueError:
            bad[column] += 1
            return None
    if kind == "int":
        try:
            return int(float(_FLOAT_JUNK.sub("", v)))
        except ValueError:
            bad[column] += 1
            return None
    raise ValueError(f"unknown kind {kind}")


_LIST_SPLIT = re.compile(r"\s*(?:;|,(?=\s*https?://)|\s/\s)\s*")


def canonical(value, kind: str):
    """The form a value is hashed in. List cells are compared as sorted sets, because the publisher reorders list
    items (trade agreements, regions, attachment URLs, end users) between files without changing them."""
    if value is None:
        return ""
    if kind == "multi":
        return "\x1e".join(sorted(p for p in _LIST_SPLIT.split(str(value)) if p))
    return str(value)


def row_hash(values: list, kinds: list[str] | None = None) -> str:
    kinds = kinds or ["str"] * len(values)
    h = hashlib.sha1()
    for v, k in zip(values, kinds):
        h.update(canonical(v, k).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def typed_rows(records: Iterable[dict], spec: list[tuple[str, str, str]], partition: tuple[str, ...],
               source_file: str, run_date: dt.date, stats: Counter, bad: Counter) -> Iterator[dict]:
    """Published records (dicts keyed by source column) to stored rows with provenance."""
    for rec in records:
        stats["read"] += 1
        row = {name: convert(rec.get(src), kind, bad, name) for name, src, kind in spec}
        d = next((row[f] for f in partition if row.get(f)), None)
        row["fiscal_year"] = common.fiscal_year(d)
        row["source_file"] = source_file
        row["row_hash"] = row_hash([row[name] for name, _s, _k in spec], [k for _n, _s, k in spec])
        row["first_seen"] = run_date
        yield row


def csv_records(path: Path, spec: list[tuple[str, str, str]], notes: list[str]) -> Iterator[dict]:
    """Records of a published CSV (UTF-8, BOM tolerated). Notes columns the spec expects but the file lacks, and
    columns the file has that nothing reads, so a change in the publisher's layout shows in the run log."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        wanted = {src for _n, src, _k in spec}
        missing = sorted(wanted - set(header))
        if missing:
            notes.append(f"{path.name}: columns missing from the file: {', '.join(missing)}")
        known_french = {h for h in header if h.endswith("-fra") or h.endswith("-fr")}
        extra = sorted(set(header) - wanted - known_french - IGNORED_COLUMNS)
        if extra:
            notes.append(f"{path.name}: new columns not stored: {', '.join(extra)}")
        yield from reader


# Published columns deliberately not stored (addresses of buyers and contacts, fax numbers, internal ids).
IGNORED_COLUMNS = {
    "contractingEntityAddressLine-ligneAdresseEntiteContractante-eng",
    "contractingEntityAddressPostalCode-entiteContractanteAdresseCodePostal",
    "contractingEntityAddressCountry-entiteContractanteAdressePays-eng",
    "contractingEntityAddressCity-entiteContractanteAdresseVille-eng",
    "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-eng",
    "contactInfoFax", "contactInfoAddressLine-contactInfoAdresseLigne-eng", "contactInfoCity-contacterInfoVille-eng",
    "contactInfoProvince-contacterInfoProvince-eng", "contactInfoPostalcode", "contactInfoCountry-contactInfoPays-eng",
    "supplierAddressLine-ligneAdresseFournisseur-eng", "_id", "Award", "Supplier Address",
}


# --------------------------------------------------------------------------- staging

def stage(rows: Iterable[dict], spec, staging: Path) -> Path:
    """Write rows to one staging Parquet file (any number of rows, in batches). Returns its path."""
    schema = arrow_schema(spec)
    staging.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(staging, schema, compression="zstd")
    batch: list[dict] = []
    try:
        for r in rows:
            batch.append(r)
            if len(batch) >= BATCH_ROWS:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch = []
        writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    finally:
        writer.close()
    return staging


# --------------------------------------------------------------------------- writing with the size cap

def write_capped(con: duckdb.DuckDBPyConnection, select_sql: str, target: Path, order_by: str) -> list[Path]:
    """Write `select_sql` ordered by `order_by` to `target` (stem.parquet), or to stem-1.parquet, stem-2.parquet,
    ... when one file would pass the size cap. Removes the stem's stale parts. Returns the files written
    (none when the query has no rows)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    stem = target.stem
    tmp = target.with_name(f".{stem}.tmp.parquet")
    con.execute(f"COPY ({select_sql} ORDER BY {order_by}) TO '{tmp.as_posix()}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 50000)")
    n_rows = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()[0]
    old = [p for p in target.parent.glob(f"{stem}*.parquet") if re.fullmatch(rf"{re.escape(stem)}(-\d+)?\.parquet", p.name)]
    if n_rows == 0:
        tmp.unlink()
        for p in old:
            p.unlink()
        return []
    size = tmp.stat().st_size
    if size <= common.MAX_FILE_BYTES:
        for p in old:
            if p != target:
                p.unlink()
        if target.exists() and _same_content(con, tmp, target):
            tmp.unlink()            # identical rows: keep the old bytes, so git sees no change
        else:
            tmp.replace(target)
        return [target]
    parts = math.ceil(size / common.SPLIT_TARGET_BYTES)
    per = math.ceil(n_rows / parts)
    written = []
    for i in range(parts):
        out = target.with_name(f"{stem}-{i + 1}.parquet")
        con.execute(f"COPY (SELECT * FROM read_parquet('{tmp.as_posix()}') LIMIT {per} OFFSET {i * per}) "
                    f"TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 50000)")
        if out.stat().st_size > common.MAX_FILE_BYTES:
            raise RuntimeError(f"{out} is still over the size cap after splitting into {parts} parts")
        written.append(out)
    for p in old:
        if p not in written:
            p.unlink()
    tmp.unlink()
    return written


def _same_content(con, a: Path, b: Path) -> bool:
    """True when two Parquet files hold the same columns (names and types) and the same rows in the same order."""
    ra, rb = f"read_parquet('{a.as_posix()}')", f"read_parquet('{b.as_posix()}')"
    if con.execute(f"DESCRIBE SELECT * FROM {ra}").fetchall() != con.execute(f"DESCRIBE SELECT * FROM {rb}").fetchall():
        return False
    na, nb = (con.execute(f"SELECT count(*) FROM {r}").fetchone()[0] for r in (ra, rb))
    if na != nb:
        return False
    diff = con.execute(f"""SELECT count(*) FROM (SELECT *, row_number() OVER () AS _n FROM {ra}
                            EXCEPT ALL SELECT *, row_number() OVER () AS _n FROM {rb})""").fetchone()[0]
    return diff == 0


# --------------------------------------------------------------------------- the three writes

def known(con, root: Path, exclude: Iterable[Path] = ()) -> str:
    """A SQL relation (row_hash, first_seen) over every stored row of the table, minus the files in `exclude`."""
    ex = {p.resolve() for p in exclude}
    files = [p for p in parquet_files(root) if p.resolve() not in ex]
    if not files:
        return "(SELECT NULL::VARCHAR AS row_hash, NULL::DATE AS first_seen WHERE false)"
    return f"(SELECT row_hash, min(first_seen) AS first_seen FROM read_parquet({sql_list(files)}) GROUP BY row_hash)"


def write_base(con, root: Path, staging: list[Path], fys: list[str] | None, order_by: str) -> dict[str, int]:
    """(Re)write <fy>/base.parquet for each fiscal year in the staging files (or only `fys`), keeping the earliest
    first_seen any stored copy of a row already had. Rows that are now in base are dropped from that fiscal year's
    monthly files and from the daily files, so a row is stored once. Returns rows written per fiscal year."""
    stg = f"read_parquet({sql_list(staging)}, union_by_name=true)"
    all_fys = [r[0] for r in con.execute(f"SELECT DISTINCT fiscal_year FROM {stg} ORDER BY 1").fetchall()]
    out = {}
    for fy in all_fys:
        if fys and fy not in fys:
            continue
        base = root / fy / "base.parquet"
        prior = known(con, root)
        sql = f"""SELECT s.* REPLACE (coalesce(least(k.first_seen, s.first_seen), s.first_seen) AS first_seen)
                  FROM (SELECT * FROM {stg} WHERE fiscal_year = '{fy}'
                        QUALIFY row_number() OVER (PARTITION BY row_hash ORDER BY source_file) = 1) s
                  LEFT JOIN {prior} k USING (row_hash)"""
        files = write_capped(con, sql, base, order_by)
        out[fy] = sum(con.execute(f"SELECT count(*) FROM read_parquet('{p.as_posix()}')").fetchone()[0] for p in files)
        if files:
            _drop_rows_now_in(con, root, files, [p for p in (root / fy).glob("m-*.parquet")] + sorted((root / "daily").glob("*.parquet")))
    return out


def _drop_rows_now_in(con, root: Path, base_files: list[Path], others: list[Path]) -> None:
    for p in others:
        if not p.exists():
            continue
        n_dup = con.execute(f"SELECT count(*) FROM read_parquet('{p.as_posix()}') WHERE row_hash IN "
                            f"(SELECT row_hash FROM read_parquet({sql_list(base_files)}))").fetchone()[0]
        if n_dup:
            keep = (f"SELECT * FROM read_parquet('{p.as_posix()}') WHERE row_hash NOT IN "
                    f"(SELECT row_hash FROM read_parquet({sql_list(base_files)}))")
            con.execute(f"CREATE OR REPLACE TEMP TABLE _keep AS {keep}")
            p.unlink()
            if con.execute("SELECT count(*) FROM _keep").fetchone()[0]:
                write_capped(con, "SELECT * FROM _keep", p, "row_hash")


def write_daily(con, root: Path, staging: list[Path], day: dt.date, order_by: str) -> int:
    """Write daily/<day>.parquet with the staged rows no stored file has yet (today's own file excluded, so a
    re-run of the same day rewrites it). Returns the rows written."""
    target = root / "daily" / f"{day.isoformat()}.parquet"
    prior = known(con, root, exclude=[target])
    stg = f"read_parquet({sql_list(staging)}, union_by_name=true)"
    sql = f"""SELECT * REPLACE (DATE '{day.isoformat()}' AS first_seen) FROM {stg}
              WHERE row_hash NOT IN (SELECT row_hash FROM {prior})
              QUALIFY row_number() OVER (PARTITION BY row_hash ORDER BY source_file) = 1"""
    files = write_capped(con, sql, target, order_by)
    return sum(con.execute(f"SELECT count(*) FROM read_parquet('{p.as_posix()}')").fetchone()[0] for p in files)


def compact(con, root: Path, before: dt.date, order_by: str) -> dict[str, int]:
    """Fold every daily file dated before `before` into <fy>/m-<YYYY-MM>.parquet (by the day's month) and delete it.
    Returns rows moved per output file."""
    daily = sorted((root / "daily").glob("*.parquet"))
    by_month: dict[str, list[Path]] = {}
    for p in daily:
        day = dt.date.fromisoformat(p.stem[:10])
        if day < before:
            by_month.setdefault(p.stem[:7], []).append(p)
    moved = {}
    for month, files in sorted(by_month.items()):
        src = f"read_parquet({sql_list(files)}, union_by_name=true)"
        for (fy,) in con.execute(f"SELECT DISTINCT fiscal_year FROM {src}").fetchall():
            target = root / fy / f"m-{month}.parquet"
            existing = [p for p in target.parent.glob(f"m-{month}*.parquet")]
            parts = [f"SELECT * FROM {src} WHERE fiscal_year = '{fy}'"]
            if existing:
                parts.append(f"SELECT * FROM read_parquet({sql_list(existing)}, union_by_name=true)")
            con.execute(f"CREATE OR REPLACE TEMP TABLE _m AS SELECT * FROM ({' UNION ALL BY NAME '.join(parts)}) "
                        f"QUALIFY row_number() OVER (PARTITION BY row_hash ORDER BY first_seen) = 1")
            written = write_capped(con, "SELECT * FROM _m", target, order_by)
            moved[str(target.relative_to(common.data_dir()))] = sum(
                con.execute(f"SELECT count(*) FROM read_parquet('{p.as_posix()}')").fetchone()[0] for p in written)
        for p in files:
            p.unlink()
    return moved


def count_rows(con, root: Path) -> int:
    files = parquet_files(root)
    if not files:
        return 0
    return con.execute(f"SELECT count(*) FROM read_parquet({sql_list(files)}, union_by_name=true)").fetchone()[0]
