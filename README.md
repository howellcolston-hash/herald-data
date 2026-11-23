# herald-data

HERALD's market data warehouse: a complete, append-only, queryable history of the public buying HERALD sells into,
and daily views that let the desks act before tenders post. Plain Python (DuckDB, pyarrow and the standard library),
run by GitHub Actions on a schedule. Nothing here calls a model or a paid service.

Sources today: CanadaBuys tender notices, award notices and contract history (federal, 2009 on), and the City of
Toronto's solicitations and awarded contracts. Each has a card in `catalog/`.

## What runs

| workflow | when | what it does |
|---|---|---|
| `daily.yml` | every day 14:37 UTC (and by hand) | collects newly published rows (Sundays also re-reads the complete files), folds finished months, rebuilds `lines` and the views, checks file sizes, commits |
| `backfill.yml` | by hand (Actions tab → backfill → Run workflow) | rebuilds the fiscal-year base files from the full published history, optionally for some fiscal years or tables only |
| `tests.yml` | on every code push | offline tests on the fixtures in `tests/fixtures/` |

Each run appends one line per step to `data/_runs/<step>.jsonl`: status (`ok`, `partial`, `failed`), rows, the
periods written, the source files' row counts and any notes (a missing file, a column the publisher added, values that
would not parse). A failed collector fails the workflow, so it shows in red on the Actions tab: a daily run in which
one file can't be fetched is `partial`; one in which no file of a table can be fetched is `failed` and exits 1.

## Layout

```
collectors/          one module per source: python -m collectors.canadabuys | collectors.toronto
  common.py          HTTP with retries, paths, fiscal years, the run log, atomic writes, the 95 MB cap
herald/
  schema.py          every stored column: name, source column, type
  store.py           append-only Parquet storage: base / monthly / daily files, the size cap
  names.py           deterministic supplier and buyer matching
  lines.py           the shared lines table (python -m herald.lines)
  views.py           the daily CSV views (python -m herald.views)
  compact.py         monthly compaction (python -m herald.compact)
  db.py              DuckDB connection with a view per table (python -m herald.db)
  check.py           size guard run before each commit
ref/buyer_aliases.csv  buyer names the rules can't join (PWGSC = PSPC, DND variants, renamed departments)
catalog/             one card per dataset: source, licence, cadence, coverage, artifacts, backfill
data/                the warehouse (written only by the workflows)
views/               the desks' CSVs (written only by the workflows)
tests/               offline tests and fixtures
```

Inside `data/`, each table is stored the same way:

```
data/<source>/<table>/<fiscal year>/base.parquet       the backfill's rows for that April-March fiscal year
data/<source>/<table>/<fiscal year>/m-<YYYY-MM>.parquet rows first seen in that month (monthly compaction)
data/<source>/<table>/daily/<YYYY-MM-DD>.parquet        rows first seen that day, until the month is folded
data/lines/<source>-<table>/...                         the same files, as lines
data/_runs/<step>.jsonl                                  run log
```

Rules: Parquet with ZSTD and explicit types (dates `DATE`, amounts `DOUBLE`, counts `BIGINT`, codes `VARCHAR`); no
file over 95 MB (a bigger write is split into `base-1.parquet`, `base-2.parquet`, ...); a large file is never
rewritten daily; nothing is ever updated in place. When the publisher changes a row (an amendment, a corrected
value, a new status) the new version is stored beside the old one with its own `row_hash` and `first_seen`. Reordering
the items of a list cell (trade agreements, regions, attachment URLs) is not a change.

## Tables

All raw tables carry `fiscal_year`, `source_file`, `row_hash` and `first_seen`. Full column lists: `herald/schema.py`.

| view in DuckDB | stored at | one row per | key columns |
|---|---|---|---|
| `canadabuys_tenders` | `data/canadabuys/tenders/` | tender notice amendment | reference_number, amendment_number, solicitation_number, title, publication_date, closing_at, status, gsin, unspsc, category, notice_type, method, buyer, end_user, regions, contact, notice_url, attachments, description |
| `canadabuys_awards` | `data/canadabuys/awards/` | award notice amendment | + contract_number, award_date, start_date, end_date, contract_amount, total_contract_value, currency, instrument_type, amendment_type, supplier_legal_name and address |
| `canadabuys_contracts` | `data/canadabuys/contracts/` | contract amendment (PSPC contract history) | + procurement_number, supplier_standardized_name, supplier_operating_name, supplier_employee_count, end_user_office |
| `toronto_solicitations` | `data/toronto/solicitations/` | City of Toronto solicitation | document_number, rfx_type, issue_date, submission_deadline, category, division, description |
| `toronto_awards` | `data/toronto/awards/` | (document, awarded supplier) | document_number, supplier, award_amount, date_awarded, division |
| `lines` | `data/lines/` | any of the above, in one shape | see below |
| `lines_current` | (view) | the newest stored version of each record (every distinct Toronto row: Toronto publishes no row id) | as lines |

`lines` columns: `line_id, source, record_type` (tender, award, contract), `source_id, amendment, solicitation_key`
(links a tender to its award and contract), `contract_number, title, buyer, buyer_key, end_user, end_user_key,
gsin, gsin_description, gsin_class, unspsc, unspsc_description, unspsc_class, category` (goods, services,
construction, services related to goods), `is_goods, method, competitive` (competitive, non-competitive, unknown),
`notice_type, instrument_type, amendment_type, status, publication_date, closing_date, award_date, start_date,
end_date, amendment_date, value, original_value, currency, supplier, supplier_key, supplier_legal_key,
supplier_from_standardized, region, fiscal_year, first_seen, source_file, row_hash`. `is_goods` is true when the
procurement category includes goods; "services related to goods" alone (repair, overhaul, maintenance) is not goods.

Name matching (`herald/names.py`): suppliers by the files' standardized name first; otherwise the legal name, upper
cased, accents and punctuation removed, `&` spelled out, a leading THE and trailing legal forms (INC, LTD, LIMITED,
CORP, LLP, S.A., ...) dropped, the first half of a bilingual `X / X` name kept, `DBA ...` dropped, dotted initials
joined. The views also join a legal-name key to a standardized key when contract history pairs them one to one.
Buyers: a trailing `(ABC)` acronym, a leading `Department of` and trailing `Canada`/`Agency` dropped, then
`ref/buyer_aliases.csv`. No model, no fuzzy scores.

## Views (`views/`, rebuilt every day)

| file | one row per | what to read |
|---|---|---|
| `retender_forecast.csv` | goods (or goods-related services) contract, standing offer or supply arrangement ending in the next 12 months | `expected_notice_from` / `expected_notice_to` (when the buyer's replacement tender should appear, from that department's own history of tender-to-award times), `notice_status` (upcoming, window open, window passed), `end_date`, `term_days` (start to end: many goods contracts are one-off purchases whose end date is delivery or a one-year warranty; standing offers and multi-year terms are the likeliest to be re-tendered), `buyer`, `category`, `procurement_category` (goods, services related to goods, ...), `gsin`, `unspsc`, `instrument_type`, `incumbent`, `value` (blank when the files publish only a $0 or $1 placeholder, as most standing offers and supply arrangements do), `award_date`, `competitive`, `original_tender_date`, `earlier_tender_dates` (the department's last five tenders in the same class), `possible_replacement_tender` (a tender the same department posted in the same class since the award, in the last year), `window_basis` and `window_basis_deals` (department, class or all goods, and how many linked deals that rests on), `typical_notice_to_award_days`, `title`, `contract_number`. Sorted most urgent first: open windows (soonest-closing first), then upcoming ones (soonest-opening first), then passed ones; value breaks ties. |
| `category_book.csv` | GSIN class or UNSPSC class | deals and value in total and for each of the last five fiscal years, `by_fiscal_year` (full history), `value_p25`/`value_median`/`value_p75`, `share_non_competitive`, `distinct_winners`, `top_winners` (top three by deal count), `peak_award_months`, tenders and the last tender date. Sorted by total value. |
| `buyer_profiles.csv` | buying department (the end user when PSPC buys for it) | recent deals and value (this fiscal year and the three before), goods share, tenders per month, days between tender days, busiest months, top categories and suppliers, deal size median/p75/max, `median_notice_to_award_days` (with its sample size), days tenders stay open, share non-competitive, share bought through PSPC. Sorted by recent value. |
| `counts.csv` | source, record type, fiscal year | lines and records stored, last `first_seen`: for checking loads |

The rules behind the views (current version, deals, departments, lead times, the notice window) are written out at
the top of `herald/views.py`, marked provisional.

## Querying with DuckDB

```bash
git clone --depth 1 https://github.com/howellcolston-hash/herald-data && cd herald-data   # latest files only: about a 160 MB download
pip install -r requirements.txt
python -m herald.db                      # row count of every view
```

The views alone need no setup: `views/*.csv` are plain sorted CSVs (or read them straight from
`https://raw.githubusercontent.com/howellcolston-hash/herald-data/main/views/<file>.csv`).

```python
from herald.db import connect
con = connect()

# every goods tender Correctional Service of Canada posted since 2024
con.sql("""SELECT publication_date, title, gsin_description, unspsc_description, closing_date
           FROM lines_current WHERE record_type = 'tender' AND is_goods
             AND end_user_key = 'CORRECTIONAL SERVICE' AND publication_date >= '2024-04-01'
           ORDER BY publication_date DESC""").show()

# who wins office furniture (GSIN N7110), by deals and value
con.sql("""SELECT supplier_key, count(*) AS deals, round(sum(value)) AS value
           FROM lines_current WHERE record_type IN ('award', 'contract') AND gsin_class = 'N7110'
             AND amendment = '000' GROUP BY 1 ORDER BY 2 DESC LIMIT 15""").show()

# every stored version of one award notice (amendment history)
con.sql("""SELECT amendment_number, status, first_seen, source_file FROM canadabuys_awards
           WHERE reference_number = 'W8484-127434:001:EEM' ORDER BY first_seen""").show()
```

Without the helper, plain DuckDB reads the files directly:

```sql
SELECT * FROM read_parquet('data/lines/**/*.parquet', union_by_name = true) LIMIT 10;
SELECT * FROM read_csv('views/retender_forecast.csv') WHERE notice_status <> 'window passed' LIMIT 20;
```

## Known gaps

- **Totals only, no unit prices.** Award and contract values are contract totals (or an amendment's amount); the
  files carry no quantities or item prices.
- **End user often blank.** Many non-PSPC notices and CanadaBuys award notices leave the end user empty, so the
  department is the contracting entity there.
- **PSPC shown as buyer for many departments.** PSPC (Public Works and Government Services Canada) buys on behalf of
  most departments; in the legacy files and in contract history it is always the contracting entity. The views read
  the end user as the department when PSPC is the buyer (`share_bought_through_pspc` shows how much).
- **Codes changed in 2022.** Legacy records carry GSIN codes; CanadaBuys records mostly UNSPSC. The category book
  keeps the two schemes apart, so a class's history before or after 2022 may sit under the other scheme.
- **Award notices repeat contract history.** About 109,000 award notices describe a contract also in contract
  history; the views keep one (the contract-history copy). `lines` keeps both.
- **Currencies.** Values are summed only for CAD (and blank-currency) rows; legacy awards include USD, EUR and others.
- **Contract history refreshes about monthly**, so recent PSPC contracts can lag by weeks; award notices fill part
  of the gap.
- **Toronto** carries no commodity codes and its solicitations file holds mostly 2022 on. It publishes no row id, so a
  row the City corrects shows as a second row.
- **Standing offers and supply arrangements carry no value** (call-ups are published separately, if at all); about a
  fifth of the forecast has a blank value for that reason.
- **The forecast cannot tell a one-off purchase from a supply period.** It lists every goods deal ending within a year;
  use `term_days`, `instrument_type` and `earlier_tender_dates` to judge whether the buyer buys it again.
  `possible_replacement_tender` matches on department and class only, so for large buyers (DND) it is often a
  different item in the same class.
- **Not yet collected:** SEAO (Québec: OCDS JSON monthly files since 2021, about 4 GB, and XML files 2009 to 2024
  on Données Québec, package `systeme-electronique-dappel-doffres-seao`), other provinces and municipalities beyond
  what CanadaBuys republishes.

## Running locally

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .
export HERALD_DATA_DIR=/tmp/herald HERALD_VIEWS_DIR=/tmp/herald-views   # keep local runs out of the repo
python -m collectors.canadabuys --backfill && python -m collectors.toronto --backfill
python -m herald.lines && python -m herald.views
```

A full backfill downloads about 2 GB of CSV and takes a few minutes. Licences: Open Government Licence - Canada;
Open Government Licence - Toronto (see the catalog cards).
