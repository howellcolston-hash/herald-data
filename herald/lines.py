"""The shared `lines` table: one row per notice, award or contract line, from every source, in one shape.

    python -m herald.lines            build the lines files that are missing or out of date
    python -m herald.lines --rebuild  rebuild all of them (after a change to the rules below or in herald/names.py)

`lines` mirrors the stored tables file for file: data/<source>/<table>/<path> becomes
data/lines/<source>-<table>/<path>, so lines are append-only and partitioned by fiscal year exactly like their
sources, and a daily run only builds the day's new file. data/lines/_state.json records which source file (by
content hash) and which LINES_VERSION each lines file was built from.

Columns (all sources):
  line_id, source, record_type (tender | award | contract), source_id, amendment, solicitation_key, contract_number,
  title, buyer, buyer_key, end_user, end_user_key, gsin, gsin_description, gsin_class, unspsc, unspsc_description,
  unspsc_class, category, is_goods, method, competitive (competitive | non-competitive | unknown), notice_type,
  instrument_type, amendment_type, status, publication_date, closing_date, award_date, start_date, end_date, amendment_date,
  value, original_value, currency, supplier, supplier_key, supplier_legal_key, supplier_from_standardized, region,
  fiscal_year, first_seen, source_file, row_hash

is_goods: CanadaBuys rows whose procurement category includes "goods" ("services related to goods" alone, such as
repair and overhaul, is not goods); Toronto rows in the City's "Goods and Services" category.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import duckdb
import pyarrow as pa

from collectors import common
from herald import names, store

LINES_VERSION = 2          # bump when the SQL below or herald/names.py changes what a line holds
#                            2: is_goods no longer true for "services related to goods" alone
ORDER_BY = "source_id, amendment, row_hash"

_N_CLASS = re.compile(r"^N\d{4}")
_GSIN_GROUP = re.compile(r"^([A-Z]{1,2}\d{2,3}|\d{4})")


def first_part(s: str | None) -> str | None:
    if not s:
        return None
    return s.split(";")[0].strip() or None


def gsin_class(code: str | None) -> str | None:
    """GSIN goods codes 'N7030', 'N9140A' -> the FSC class 'N7030'; service and construction codes 'R008A',
    '5164AB', 'AA910300' -> their leading group 'R008', '5164', 'AA910'. PROVISIONAL grouping."""
    c = first_part(code)
    if not c:
        return None
    c = c.upper()
    m = _N_CLASS.match(c)
    if m:
        return m.group(0)
    m = _GSIN_GROUP.match(c)
    return m.group(1) if m else c[:4]


def unspsc_class(code: str | None) -> str | None:
    """UNSPSC commodity '43211503' -> class '43211500' (segment, family and class digits)."""
    c = first_part(code)
    if not c:
        return None
    digits = re.sub(r"\D", "", c)
    if len(digits) < 6:
        return None
    return digits[:6] + "00"


def solicitation_key(s: str | None) -> str | None:
    """Links tenders, awards and contracts: upper case, no spaces, the part before the first '/'
    ('W6399-13EA54/A' and 'W6399-13EA54' both give 'W6399-13EA54')."""
    if not s:
        return None
    k = s.upper().replace(" ", "").split("/")[0].split(":")[0]
    return k or None


_CATEGORY = {"GD": "goods", "SRV": "services", "CNST": "construction", "SRVTGD": "services related to goods"}


def category_words(s: str | None) -> str | None:
    if not s:
        return None
    out = []
    for part in s.split(";"):
        p = part.strip().upper()
        out.append(_CATEGORY.get(p, part.strip().lower()))
    return "; ".join(dict.fromkeys(o for o in out if o)) or None


def competitive(method: str | None, notice_type: str | None) -> str:
    m = (method or "").lower()
    n = (notice_type or "").lower()
    if m.startswith("non-competitive") or "advance contract award" in m or "directed contract" in n \
            or "advance contract award" in n:
        return "non-competitive"
    if m.startswith("competitive"):
        return "competitive"
    return "unknown"


# The Python rules above (and herald/names.py) are applied to each source file's distinct values, and the results
# are added to the staged rows as the columns below, so the SQL that shapes a line only reads columns. (DuckDB's
# Python functions would need numpy, which this repository does not depend on.)
_CODES = {
    "_gsin": (first_part, ["gsin"]), "_gsin_description": (first_part, ["gsin_description"]),
    "_gsin_class": (gsin_class, ["gsin"]), "_unspsc": (first_part, ["unspsc"]),
    "_unspsc_description": (first_part, ["unspsc_description"]), "_unspsc_class": (unspsc_class, ["unspsc"]),
    "_category": (category_words, ["category"]), "_competitive": (competitive, ["method", "notice_type"]),
    "_buyer_key": (names.buyer_key, ["buyer"]), "_end_user_key": (names.buyer_key, ["end_user"]),
}
DERIVED = {
    ("canadabuys", "tenders"): _CODES | {
        "_solicitation_key": (solicitation_key, ["coalesce(solicitation_number, reference_number)"])},
    ("canadabuys", "awards"): _CODES | {
        "_solicitation_key": (solicitation_key, ["coalesce(solicitation_number, contract_number)"]),
        "_supplier_key": (names.supplier_key, ["supplier_legal_name"])},
    ("canadabuys", "contracts"): _CODES | {
        "_solicitation_key": (solicitation_key, ["coalesce(procurement_number, solicitation_number, contract_number)"]),
        "_supplier_key": (names.supplier_key, ["coalesce(supplier_standardized_name, supplier_legal_name)"]),
        "_supplier_legal_key": (names.supplier_key, ["supplier_legal_name"])},
    ("toronto", "solicitations"): {
        "_end_user_key": (names.buyer_key, ["division"]), "_solicitation_key": (solicitation_key, ["document_number"])},
    ("toronto", "awards"): {
        "_end_user_key": (names.buyer_key, ["division"]), "_solicitation_key": (solicitation_key, ["document_number"]),
        "_supplier_key": (names.supplier_key, ["supplier"])},
}


def add_derived(con: duckdb.DuckDBPyConnection, table: str, derived: dict) -> None:
    """Add each derived column to `table`: the rule is run once per distinct input, then joined back."""
    for col, (fn, exprs) in derived.items():
        inputs = con.execute(f"SELECT DISTINCT {', '.join(exprs)} FROM {table}").fetchall()
        mapping = pa.table({**{f"i{n}": pa.array([r[n] for r in inputs], pa.string()) for n in range(len(exprs))},
                            "o": pa.array([fn(*r) for r in inputs], pa.string())})
        con.register("_map", mapping)
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR")
        cond = " AND ".join(f"({e}) IS NOT DISTINCT FROM _map.i{n}" for n, e in enumerate(exprs))
        con.execute(f"UPDATE {table} SET {col} = _map.o FROM _map WHERE {cond}")
        con.unregister("_map")


_COMMON = """
    _gsin AS gsin, _gsin_description AS gsin_description, _gsin_class AS gsin_class,
    _unspsc AS unspsc, _unspsc_description AS unspsc_description, _unspsc_class AS unspsc_class,
    _category AS category, coalesce(list_contains(string_split(_category, '; '), 'goods'), false) AS is_goods,
    method, _competitive AS competitive, notice_type,
"""
_TAIL = "fiscal_year, first_seen, source_file, row_hash"

SQL = {
    ("canadabuys", "tenders"): f"""
        SELECT 'canadabuys' AS source, 'tender' AS record_type, reference_number AS source_id,
               amendment_number AS amendment, _solicitation_key AS solicitation_key,
               NULL::VARCHAR AS contract_number, title, buyer, _buyer_key AS buyer_key,
               end_user, _end_user_key AS end_user_key, {_COMMON}
               NULL::VARCHAR AS instrument_type, NULL::VARCHAR AS amendment_type, status, publication_date,
               CAST(closing_at AS DATE) AS closing_date, NULL::DATE AS award_date, expected_start_date AS start_date,
               expected_end_date AS end_date, amendment_date, NULL::DOUBLE AS value, NULL::DOUBLE AS original_value,
               NULL::VARCHAR AS currency, NULL::VARCHAR AS supplier, NULL::VARCHAR AS supplier_key,
               NULL::VARCHAR AS supplier_legal_key, false AS supplier_from_standardized,
               regions_of_delivery AS region, {_TAIL}
        FROM src""",
    ("canadabuys", "awards"): f"""
        SELECT 'canadabuys' AS source, 'award' AS record_type, reference_number AS source_id,
               amendment_number AS amendment, _solicitation_key AS solicitation_key, contract_number, title, buyer,
               _buyer_key AS buyer_key, end_user, _end_user_key AS end_user_key, {_COMMON}
               instrument_type, amendment_type, status, publication_date, NULL::DATE AS closing_date, award_date,
               start_date, end_date, amendment_date,
               CASE WHEN total_contract_value > 0 THEN total_contract_value ELSE contract_amount END AS value,
               contract_amount AS original_value, currency, supplier_legal_name AS supplier,
               _supplier_key AS supplier_key, _supplier_key AS supplier_legal_key,
               false AS supplier_from_standardized, regions_of_delivery AS region, {_TAIL}
        FROM src""",
    ("canadabuys", "contracts"): f"""
        SELECT 'canadabuys' AS source, 'contract' AS record_type, reference_number AS source_id,
               amendment_number AS amendment, _solicitation_key AS solicitation_key, contract_number, title, buyer,
               _buyer_key AS buyer_key, end_user, _end_user_key AS end_user_key, {_COMMON}
               instrument_type, amendment_type, status, publication_date, NULL::DATE AS closing_date, award_date,
               start_date, end_date, amendment_date,
               CASE WHEN total_contract_value > 0 THEN total_contract_value ELSE contract_amount END AS value,
               contract_amount AS original_value, coalesce(currency, 'CAD') AS currency,
               coalesce(supplier_standardized_name, supplier_legal_name) AS supplier,
               _supplier_key AS supplier_key, _supplier_legal_key AS supplier_legal_key,
               supplier_standardized_name IS NOT NULL AS supplier_from_standardized,
               regions_of_delivery AS region, {_TAIL}
        FROM src""",
    ("toronto", "solicitations"): f"""
        SELECT 'toronto' AS source, 'tender' AS record_type, document_number AS source_id, '000' AS amendment,
               _solicitation_key AS solicitation_key, NULL::VARCHAR AS contract_number,
               left(description, 300) AS title, 'City of Toronto' AS buyer, 'CITY OF TORONTO' AS buyer_key,
               division AS end_user, _end_user_key AS end_user_key,
               NULL::VARCHAR AS gsin, NULL::VARCHAR AS gsin_description, NULL::VARCHAR AS gsin_class,
               NULL::VARCHAR AS unspsc, NULL::VARCHAR AS unspsc_description, NULL::VARCHAR AS unspsc_class,
               lower(category) AS category, coalesce(lower(category) LIKE '%goods%', false) AS is_goods,
               rfx_type AS method, 'competitive' AS competitive, noip_type AS notice_type,
               NULL::VARCHAR AS instrument_type, NULL::VARCHAR AS amendment_type, NULL::VARCHAR AS status,
               issue_date AS publication_date, submission_deadline AS closing_date, NULL::DATE AS award_date,
               NULL::DATE AS start_date, NULL::DATE AS end_date, NULL::DATE AS amendment_date, NULL::DOUBLE AS value,
               NULL::DOUBLE AS original_value, NULL::VARCHAR AS currency, NULL::VARCHAR AS supplier,
               NULL::VARCHAR AS supplier_key, NULL::VARCHAR AS supplier_legal_key, false AS supplier_from_standardized,
               wards AS region, {_TAIL}
        FROM src""",
    ("toronto", "awards"): f"""
        SELECT 'toronto' AS source, 'award' AS record_type, document_number AS source_id, '000' AS amendment,
               _solicitation_key AS solicitation_key, NULL::VARCHAR AS contract_number,
               left(description, 300) AS title, 'City of Toronto' AS buyer, 'CITY OF TORONTO' AS buyer_key,
               division AS end_user, _end_user_key AS end_user_key,
               NULL::VARCHAR AS gsin, NULL::VARCHAR AS gsin_description, NULL::VARCHAR AS gsin_class,
               NULL::VARCHAR AS unspsc, NULL::VARCHAR AS unspsc_description, NULL::VARCHAR AS unspsc_class,
               lower(category) AS category, coalesce(lower(category) LIKE '%goods%', false) AS is_goods,
               rfx_type AS method, 'competitive' AS competitive, NULL::VARCHAR AS notice_type,
               NULL::VARCHAR AS instrument_type, NULL::VARCHAR AS amendment_type,
               CASE WHEN cancellation_date IS NOT NULL THEN 'Cancelled' END AS status,
               NULL::DATE AS publication_date, NULL::DATE AS closing_date,
               coalesce(date_awarded, award_authority_date) AS award_date, NULL::DATE AS start_date,
               NULL::DATE AS end_date, NULL::DATE AS amendment_date, award_amount AS value,
               initial_contract_value AS original_value, 'CAD' AS currency, supplier,
               _supplier_key AS supplier_key, _supplier_key AS supplier_legal_key,
               false AS supplier_from_standardized, wards AS region, {_TAIL}
        FROM src""",
}


def lines_root() -> Path:
    return common.data_dir() / "lines"


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(rebuild: bool = False, con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Bring data/lines up to date with the stored tables. Returns counts of files built, kept and removed."""
    con = con or duckdb.connect()
    root = lines_root()
    state_path = root / "_state.json"
    state = {} if rebuild else common.read_json(state_path)
    wanted: dict[str, Path] = {}
    built = kept = 0
    for (source, table), sql in SQL.items():
        troot = store.table_root(source, table)
        for raw in store.parquet_files(troot):
            rel = raw.relative_to(troot)
            out_rel = f"{source}-{table}/{rel.as_posix()}"
            out = root / out_rel
            wanted[out_rel] = out
            digest = _sha1(raw)
            if not rebuild and state.get(out_rel) == {"sha1": digest, "version": LINES_VERSION} and out.exists():
                kept += 1
                continue
            con.execute(f"CREATE OR REPLACE TEMP TABLE src AS SELECT * FROM read_parquet('{raw.as_posix()}')")
            add_derived(con, "src", DERIVED[(source, table)])
            select = f"SELECT md5(source || ':' || record_type || ':' || row_hash) AS line_id, * FROM ({sql})"
            store.write_capped(con, select, out, ORDER_BY)
            state[out_rel] = {"sha1": digest, "version": LINES_VERSION}
            built += 1
    removed = 0
    for p in store.parquet_files(root):
        rel = p.relative_to(root).as_posix()
        base_rel = re.sub(r"-\d+\.parquet$", ".parquet", rel)
        if rel not in wanted and base_rel not in wanted:
            p.unlink()
            removed += 1
    state = {k: v for k, v in state.items() if k in wanted}
    common.write_json(state_path, state)
    return {"built": built, "kept": kept, "removed": removed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m herald.lines", description=__doc__.split("\n\n")[0])
    ap.add_argument("--rebuild", action="store_true", help="rebuild every lines file")
    args = ap.parse_args(argv)
    with common.run("lines", {"rebuild": args.rebuild}) as ctx:
        con = duckdb.connect()
        res = build(args.rebuild, con)
        files = store.parquet_files(lines_root())
        n = con.execute(f"SELECT count(*) FROM read_parquet({store.sql_list(files)}, union_by_name=true)").fetchone()[0] if files else 0
        ctx["rows"] = n
        ctx["counts"] = res | {"lines": n}
        ctx["notes"].append(f"{res['built']} files built, {res['kept']} unchanged, {res['removed']} removed; {n} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
