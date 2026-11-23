# lines (derived)

- **What:** one row per notice, award or contract line from every collected source, in one shape: buyer, end user, department keys, GSIN, UNSPSC and their classes, category, method, competitive or not, dates, value, supplier and its matching key, source and source id. Columns: `herald/lines.py` docstring.
- **Built by:** `python -m herald.lines` from the stored tables, file for file (`data/lines/<source>-<table>/...` mirrors `data/<source>/<table>/...`), so it is append-only and partitioned by fiscal year like its sources.
- **Licence:** as each source (Open Government Licence - Canada; Open Government Licence - Toronto).
- **Matching:** suppliers by the files' standardized name first, then the deterministic rules in `herald/names.py`; buyers by the rules there and `ref/buyer_aliases.csv`. No model.
- **Known artifacts:** inherits each source's gaps (README.md, "Known gaps"). `value` is the stated total when positive, else the line's amount; it is a contract total, never a unit price.
- **Backfill:** rebuilt from the stored tables at any time (`--rebuild`).
