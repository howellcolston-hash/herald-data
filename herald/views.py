"""Daily views for the desks: small sorted CSVs under views/, rebuilt from `lines` on every run.

    python -m herald.views [--today YYYY-MM-DD]

views/retender_forecast.csv  goods contracts and standing offers ending in the next 12 months, with buyer, category,
                             incumbent, value, earlier tender dates, the expected notice window from that buyer's
                             history, and any tender the same buyer posted in the same class since the award and in
                             the last year (possibly the replacement, already out)
views/category_book.csv      per GSIN class and UNSPSC class: count and value by fiscal year, typical size, share
                             non-competitive, distinct and top winners, peak award months
views/buyer_profiles.csv     per buying department: categories, cadence, sizes, typical time from notice to award
views/counts.csv             rows per source, record type and fiscal year, for checking loads

How the views read `lines` (all PROVISIONAL, set out here so they can be argued with):
  * Current version: of the stored versions of one record (source, record type, source id, amendment), the one first
    seen last; on a tie, the newer published file. Toronto publishes no row id (one document can list several
    awarded suppliers), so every distinct Toronto row is its own record.
  * Deal: the amendments of one contract or award, keyed by its contract number (':' read as '/'), else its source
    id. Award notices whose deal also appears in contract history are dropped (contract history is fuller). A deal's
    value is the larger of its highest stated total and the sum of its amendment amounts; its end date is the latest
    end date before 2100; a deal with a Termination amendment or Cancelled status is ended.
  * Department: the end user when PSPC (Public Works and Government Services) is the buyer, else the buyer.
  * Supplier: the standardized-name key; a legal-name key that contract history pairs with exactly one standardized
    key is read as that key.
  * Lead time: days from a tender's first publication to the award of a deal with the same solicitation key, kept
    when 0 to 730 days.
  * Expected notice window: end date minus the 75th and 25th percentile lead time of the department (at least 5
    linked goods deals), else of the GSIN/UNSPSC class (at least 5), else of all goods deals.
  * Term: days from start (else award) to end. Many goods "contracts" are one-off purchases whose end date is the
    delivery date or the end of a one-year warranty, and may never be tendered again; standing offers and terms of
    two years or more are supply periods, the likeliest to be re-tendered.
  * Values are summed only for CAD (or blank-currency) rows; amounts are what the files publish (totals, not unit
    prices). A deal value under $100 is a placeholder (standing offers and supply arrangements usually publish $0,
    some $1): the forecast shows it blank and the typical-size figures leave it out.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb

from collectors import common
from herald import store
from herald.lines import lines_root

PSPC_KEY = "PUBLIC WORKS AND GOVERNMENT SERVICES"
MIN_LINKED = 5
FORECAST_DAYS = 365
MIN_VALUE = 100          # deal values below this are placeholders ($0 standing offers, $1 lines), not amounts


def setup(con: duckdb.DuckDBPyConnection, today: dt.date) -> None:
    files = store.parquet_files(lines_root())
    if not files:
        raise RuntimeError("no lines files: run python -m herald.lines first")
    con.execute(f"CREATE OR REPLACE VIEW lines AS SELECT * FROM read_parquet({store.sql_list(files)}, union_by_name=true)")
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE cur AS
    SELECT *,
           CASE WHEN buyer_key = '{PSPC_KEY}' AND end_user_key IS NOT NULL THEN end_user_key ELSE buyer_key END AS dept_key,
           CASE WHEN buyer_key = '{PSPC_KEY}' AND end_user_key IS NOT NULL THEN first_part_s(end_user) ELSE buyer END AS dept_name,
           (currency IS NULL OR currency = 'CAD') AS is_cad
    FROM (SELECT * REPLACE (CASE WHEN end_date >= DATE '2100-01-01' OR end_date < DATE '1990-01-01' THEN NULL ELSE end_date END AS end_date,
                            -- exact cents, so sums don't depend on the order rows are added in
                            CAST(round(value, 2) AS DECIMAL(18, 2)) AS value,
                            CAST(round(original_value, 2) AS DECIMAL(18, 2)) AS original_value)
          FROM lines
          QUALIFY row_number() OVER (PARTITION BY source, record_type, source_id, amendment,
                                                  CASE WHEN source = 'toronto' THEN row_hash END
                                     ORDER BY first_seen DESC, source_file DESC, row_hash) = 1)""")
    # supplier map: legal-name keys paired with exactly one standardized key in contract history
    con.execute("""
    CREATE OR REPLACE TEMP TABLE supplier_map AS
    SELECT supplier_legal_key AS legal_key, any_value(supplier_key) AS std_key FROM cur
    WHERE record_type = 'contract' AND supplier_from_standardized AND supplier_legal_key IS NOT NULL
    GROUP BY 1 HAVING count(DISTINCT supplier_key) = 1""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE cur2 AS
    SELECT c.*, coalesce(m.std_key, c.supplier_key) AS supplier_uid FROM cur c
    LEFT JOIN supplier_map m ON c.supplier_legal_key = m.legal_key AND NOT c.supplier_from_standardized""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE supplier_names AS
    SELECT supplier_uid, supplier AS supplier_name FROM (
      SELECT supplier_uid, supplier, count(*) AS n FROM cur2 WHERE supplier_uid IS NOT NULL AND supplier IS NOT NULL GROUP BY 1, 2)
    QUALIFY row_number() OVER (PARTITION BY supplier_uid ORDER BY n DESC, supplier) = 1""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE dept_names AS
    SELECT dept_key, dept_name AS dept_display FROM (
      SELECT dept_key, dept_name, count(*) AS n FROM cur2 WHERE dept_key IS NOT NULL AND dept_name IS NOT NULL GROUP BY 1, 2)
    QUALIFY row_number() OVER (PARTITION BY dept_key ORDER BY n DESC, dept_name) = 1""")
    # deals
    con.execute("""
    CREATE OR REPLACE TEMP TABLE deal_lines AS
    SELECT *, source || ':' || upper(replace(replace(coalesce(contract_number, source_id), ':', '/'), ' ', '')) AS deal_id,
           amendment || '|' || source_id || '|' || row_hash AS ok
    FROM cur2 WHERE record_type IN ('award', 'contract')""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE deals AS
    WITH d AS (
      SELECT deal_id, source, record_type,
             arg_max(source_id, ok) AS source_id, max(contract_number) AS contract_number,
             arg_min(title, ok) AS title, arg_min(dept_key, ok) AS dept_key, arg_min(buyer, ok) AS buyer,
             arg_min(supplier_uid, ok) AS supplier_uid,
             arg_min(gsin, ok) AS gsin, arg_min(gsin_description, ok) AS gsin_description,
             arg_min(gsin_class, ok) AS gsin_class, arg_min(unspsc, ok) AS unspsc,
             arg_min(unspsc_description, ok) AS unspsc_description, arg_min(unspsc_class, ok) AS unspsc_class,
             arg_min(category, ok) AS category, bool_or(is_goods) AS is_goods,
             arg_min(method, ok) AS method, arg_min(competitive, ok) AS competitive,
             arg_max(instrument_type, ok) AS instrument_type,
             min(award_date) AS award_date, min(start_date) AS start_date, max(end_date) AS end_date,
             greatest(max(value), sum(original_value)) AS value, bool_and(is_cad) AS is_cad,
             max(solicitation_key) AS solicitation_key, count(*) AS n_amendments,
             bool_or(coalesce(status, '') = 'Cancelled' OR coalesce(amendment_type, '') = 'Termination') AS cancelled,
             max(amendment_date) AS last_amendment_date
      FROM deal_lines GROUP BY deal_id, source, record_type)
    SELECT d.* FROM d
    WHERE record_type = 'contract'
       OR deal_id NOT IN (SELECT deal_id FROM deal_lines WHERE record_type = 'contract')""")
    # tenders: one row per source id (first publication)
    con.execute("""
    CREATE OR REPLACE TEMP TABLE tenders AS
    SELECT source, source_id, min(publication_date) AS publication_date, max(closing_date) AS closing_date,
           arg_min(dept_key, amendment) AS dept_key, max(solicitation_key) AS solicitation_key,
           arg_min(gsin_class, amendment) AS gsin_class, arg_min(unspsc_class, amendment) AS unspsc_class,
           bool_or(is_goods) AS is_goods, arg_min(title, amendment) AS title, max(status) AS status,
           arg_min(notice_type, amendment) AS notice_type
    FROM cur2 WHERE record_type = 'tender' AND publication_date IS NOT NULL GROUP BY 1, 2""")
    # lead times
    con.execute("""
    CREATE OR REPLACE TEMP TABLE leads AS
    WITH t AS (SELECT solicitation_key, min(publication_date) AS pub, min(closing_date) AS close
               FROM tenders WHERE solicitation_key IS NOT NULL GROUP BY 1)
    SELECT d.deal_id, d.dept_key, d.gsin_class, d.unspsc_class, d.is_goods,
           datediff('day', t.pub, d.award_date) AS lead_days, datediff('day', t.pub, t.close) AS tender_days
    FROM deals d JOIN t USING (solicitation_key)
    WHERE d.award_date IS NOT NULL AND datediff('day', t.pub, d.award_date) BETWEEN 0 AND 730""")


def retender_forecast(con, today: dt.date, out: Path) -> int:
    horizon = today + dt.timedelta(days=FORECAST_DAYS)
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE fc AS
    WITH g AS (SELECT * FROM leads WHERE is_goods),
    by_dept AS (SELECT dept_key, count(*) n, quantile_cont(lead_days, 0.25) p25, median(lead_days) p50,
                       quantile_cont(lead_days, 0.75) p75 FROM g GROUP BY 1 HAVING count(*) >= {MIN_LINKED}),
    by_gsin AS (SELECT gsin_class, count(*) n, quantile_cont(lead_days, 0.25) p25, median(lead_days) p50,
                       quantile_cont(lead_days, 0.75) p75 FROM g WHERE gsin_class IS NOT NULL GROUP BY 1
                HAVING count(*) >= {MIN_LINKED}),
    by_unspsc AS (SELECT unspsc_class, count(*) n, quantile_cont(lead_days, 0.25) p25, median(lead_days) p50,
                         quantile_cont(lead_days, 0.75) p75 FROM g WHERE unspsc_class IS NOT NULL GROUP BY 1
                  HAVING count(*) >= {MIN_LINKED}),
    allg AS (SELECT count(*) n, quantile_cont(lead_days, 0.25) p25, median(lead_days) p50,
                    quantile_cont(lead_days, 0.75) p75 FROM g),
    due AS (SELECT * FROM deals
            WHERE NOT cancelled AND end_date BETWEEN DATE '{today}' AND DATE '{horizon}'
              AND (is_goods OR coalesce(category, '') LIKE '%related to goods%')),
    prior AS (
      SELECT d.deal_id,
             string_agg(DISTINCT strftime(t.publication_date, '%Y-%m-%d'), '; ' ORDER BY strftime(t.publication_date, '%Y-%m-%d') DESC) AS earlier,
             count(*) AS n_earlier
      FROM due d JOIN tenders t
        ON t.dept_key = d.dept_key
       AND ((d.gsin_class IS NOT NULL AND t.gsin_class = d.gsin_class)
            OR (d.unspsc_class IS NOT NULL AND t.unspsc_class = d.unspsc_class))
       AND t.publication_date < coalesce(d.award_date, DATE '{today}')
      GROUP BY 1),
    linked AS (SELECT d.deal_id, min(t.publication_date) AS own_tender FROM due d
               JOIN tenders t ON t.solicitation_key = d.solicitation_key GROUP BY 1),
    recent AS (
      SELECT d.deal_id, arg_max(t.source_id || ' (' || strftime(t.publication_date, '%Y-%m-%d') || ', '
                                || coalesce(t.status, '') || '): ' || coalesce(left(t.title, 120), ''),
                                strftime(t.publication_date, '%Y-%m-%d') || t.source_id) AS recent_tender
      FROM due d JOIN tenders t
        ON t.dept_key = d.dept_key
       AND ((d.gsin_class IS NOT NULL AND t.gsin_class = d.gsin_class)
            OR (d.unspsc_class IS NOT NULL AND t.unspsc_class = d.unspsc_class))
       AND t.publication_date > coalesce(d.award_date, DATE '{today}')
       AND t.publication_date >= DATE '{today}' - 365
      GROUP BY 1)
    SELECT d.*, p.earlier, coalesce(p.n_earlier, 0) AS n_earlier, l.own_tender, r.recent_tender,
           CASE WHEN bd.n IS NOT NULL THEN 'department'
                WHEN bg.n IS NOT NULL THEN 'gsin class'
                WHEN bu.n IS NOT NULL THEN 'unspsc class' ELSE 'all goods' END AS window_basis,
           coalesce(bd.n, bg.n, bu.n, allg.n) AS basis_n,
           coalesce(bd.p25, bg.p25, bu.p25, allg.p25) AS p25,
           coalesce(bd.p50, bg.p50, bu.p50, allg.p50) AS p50,
           coalesce(bd.p75, bg.p75, bu.p75, allg.p75) AS p75
    FROM due d
    LEFT JOIN prior p USING (deal_id) LEFT JOIN linked l USING (deal_id) LEFT JOIN recent r USING (deal_id)
    LEFT JOIN by_dept bd ON bd.dept_key = d.dept_key
    LEFT JOIN by_gsin bg ON bg.gsin_class = d.gsin_class
    LEFT JOIN by_unspsc bu ON bu.unspsc_class = d.unspsc_class
    CROSS JOIN allg""")
    sql = f"""
    SELECT f.end_date - CAST(round(f.p75) AS INTEGER) AS expected_notice_from,
           f.end_date - CAST(round(f.p25) AS INTEGER) AS expected_notice_to,
           CASE WHEN f.end_date - CAST(round(f.p25) AS INTEGER) < DATE '{today}' THEN 'window passed'
                WHEN f.end_date - CAST(round(f.p75) AS INTEGER) <= DATE '{today}' THEN 'window open'
                ELSE 'upcoming' END AS notice_status,
           f.end_date, datediff('day', coalesce(f.start_date, f.award_date), f.end_date) AS term_days,
           coalesce(dn.dept_display, f.dept_key) AS buyer, f.buyer AS contracting_entity,
           coalesce(f.gsin_description, f.unspsc_description) AS category, f.category AS procurement_category,
           f.gsin, f.unspsc,
           f.instrument_type, coalesce(sn.supplier_name, f.supplier_uid) AS incumbent,
           CASE WHEN f.value >= {MIN_VALUE} THEN round(f.value, 2) END AS value,
           CASE WHEN f.is_cad THEN 'CAD' ELSE 'mixed or foreign' END AS value_currency,
           f.award_date, f.method, f.competitive, f.own_tender AS original_tender_date,
           f.earlier AS earlier_tender_dates, f.n_earlier AS n_earlier_tenders,
           f.recent_tender AS possible_replacement_tender,
           f.window_basis, f.basis_n AS window_basis_deals, round(f.p50) AS typical_notice_to_award_days,
           f.title, f.contract_number, f.source_id, f.source, f.deal_id
    FROM fc f
    LEFT JOIN dept_names dn ON dn.dept_key = f.dept_key
    LEFT JOIN supplier_names sn ON sn.supplier_uid = f.supplier_uid
    """
    con.execute(f"CREATE OR REPLACE TEMP TABLE fc_out AS {sql}")
    con.execute("""UPDATE fc_out SET earlier_tender_dates = array_to_string(list_slice(string_split(earlier_tender_dates, '; '), 1, 5), '; ')
                   WHERE earlier_tender_dates IS NOT NULL""")
    order = ("CASE notice_status WHEN 'window open' THEN 1 WHEN 'upcoming' THEN 2 ELSE 3 END, "
             "CASE WHEN notice_status = 'window open' THEN expected_notice_to ELSE expected_notice_from END, "
             "value DESC NULLS LAST, deal_id")
    return _write_csv(con, "SELECT * FROM fc_out", order, out)


def category_book(con, today: dt.date, out: Path) -> int:
    fy_now = int(common.fiscal_year(today)[:4])
    recent = [f"{y}-{y + 1}" for y in range(fy_now - 4, fy_now + 1)]
    cols = ",\n".join(
        f"count(*) FILTER (WHERE fy = '{fy}') AS \"n_{fy}\", round(sum(value) FILTER (WHERE fy = '{fy}' AND is_cad), 0) AS \"value_{fy}\""
        for fy in recent)
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE book_src AS
    SELECT 'GSIN' AS scheme, gsin_class AS class, gsin_description AS description, fiscal_year_of(award_date) AS fy, *
    FROM deals WHERE gsin_class IS NOT NULL
    UNION ALL BY NAME
    SELECT 'UNSPSC' AS scheme, unspsc_class AS class, unspsc_description AS description, fiscal_year_of(award_date) AS fy, *
    FROM deals WHERE unspsc_class IS NOT NULL""")
    sql = f"""
    WITH b AS (SELECT * FROM book_src WHERE NOT cancelled),
    dsc AS (SELECT scheme, class, description, category FROM (
              SELECT scheme, class, description, category, count(*) AS n FROM b GROUP BY ALL)
            QUALIFY row_number() OVER (PARTITION BY scheme, class ORDER BY n DESC, description NULLS LAST, category NULLS LAST) = 1),
    winners AS (
      SELECT scheme, class, supplier_uid, sum(value) FILTER (WHERE is_cad) AS v, count(*) AS n FROM b
      WHERE supplier_uid IS NOT NULL GROUP BY ALL),
    top AS (
      SELECT w.scheme, w.class,
             string_agg(coalesce(sn.supplier_name, w.supplier_uid) || ' (' || w.n || ')', '; ' ORDER BY w.n DESC, w.v DESC NULLS LAST, w.supplier_uid)
               FILTER (WHERE rk <= 3) AS top_winners
      FROM (SELECT *, row_number() OVER (PARTITION BY scheme, class ORDER BY n DESC, v DESC NULLS LAST, supplier_uid) AS rk FROM winners) w
      LEFT JOIN supplier_names sn ON sn.supplier_uid = w.supplier_uid GROUP BY 1, 2),
    months AS (
      SELECT scheme, class, string_agg(m, ', ' ORDER BY n DESC, m) FILTER (WHERE rk <= 2) AS peak_award_months FROM (
        SELECT scheme, class, strftime(award_date, '%b') AS m, count(*) AS n,
               row_number() OVER (PARTITION BY scheme, class ORDER BY count(*) DESC, strftime(award_date, '%b')) AS rk
        FROM b WHERE award_date IS NOT NULL GROUP BY scheme, class, strftime(award_date, '%b')) GROUP BY 1, 2),
    hist AS (
      SELECT scheme, class, string_agg(fy || ': ' || n || ' / ' || coalesce(CAST(v AS VARCHAR), '-'), ' | ' ORDER BY fy) AS by_fiscal_year
      FROM (SELECT scheme, class, fy, count(*) n, CAST(round(sum(value) FILTER (WHERE is_cad)) AS BIGINT) v
            FROM b WHERE fy <> 'undated' GROUP BY ALL) GROUP BY 1, 2),
    tend AS (
      SELECT 'GSIN' AS scheme, gsin_class AS class, count(*) AS n_tenders, max(publication_date) AS last_tender
      FROM tenders WHERE gsin_class IS NOT NULL GROUP BY 2
      UNION ALL
      SELECT 'UNSPSC', unspsc_class, count(*), max(publication_date) FROM tenders WHERE unspsc_class IS NOT NULL GROUP BY 2)
    SELECT b.scheme, b.class, any_value(dsc.description) AS description,
           any_value(dsc.category) AS category,
           count(*) AS n_deals, round(sum(b.value) FILTER (WHERE b.is_cad), 0) AS value_total,
           {cols},
           round(quantile_cont(b.value, 0.25) FILTER (WHERE b.is_cad AND b.value >= {MIN_VALUE}), 0) AS value_p25,
           round(median(b.value) FILTER (WHERE b.is_cad AND b.value >= {MIN_VALUE}), 0) AS value_median,
           round(quantile_cont(b.value, 0.75) FILTER (WHERE b.is_cad AND b.value >= {MIN_VALUE}), 0) AS value_p75,
           round(count(*) FILTER (WHERE b.competitive = 'non-competitive')
                 / nullif(count(*) FILTER (WHERE b.competitive <> 'unknown'), 0), 3) AS share_non_competitive,
           count(DISTINCT b.supplier_uid) AS distinct_winners,
           any_value(top.top_winners) AS top_winners, any_value(months.peak_award_months) AS peak_award_months,
           any_value(tend.n_tenders) AS n_tenders, any_value(tend.last_tender) AS last_tender_date,
           max(b.award_date) AS last_award_date, any_value(hist.by_fiscal_year) AS by_fiscal_year
    FROM b
    LEFT JOIN dsc USING (scheme, class)
    LEFT JOIN top USING (scheme, class) LEFT JOIN months USING (scheme, class)
    LEFT JOIN hist USING (scheme, class) LEFT JOIN tend USING (scheme, class)
    GROUP BY b.scheme, b.class"""
    return _write_csv(con, sql, "value_total DESC NULLS LAST, scheme, class", out)


def buyer_profiles(con, today: dt.date, out: Path) -> int:
    since = dt.date(int(common.fiscal_year(today)[:4]) - 3, 4, 1)   # the last three full fiscal years and this one
    months = (today - since).days / 30.44
    sql = f"""
    WITH d AS (SELECT * FROM deals WHERE NOT cancelled AND dept_key IS NOT NULL),
    t AS (SELECT * FROM tenders WHERE dept_key IS NOT NULL),
    cats AS (
      SELECT dept_key, string_agg(c || ' (' || n || ')', '; ' ORDER BY n DESC, c) FILTER (WHERE rk <= 3) AS top_categories FROM (
        SELECT dept_key, coalesce(gsin_description, unspsc_description) AS c, count(*) n,
               row_number() OVER (PARTITION BY dept_key ORDER BY count(*) DESC, coalesce(gsin_description, unspsc_description)) AS rk
        FROM d WHERE coalesce(gsin_description, unspsc_description) IS NOT NULL AND award_date >= DATE '{since}'
        GROUP BY 1, 2) GROUP BY 1),
    sup AS (
      SELECT dept_key, string_agg(coalesce(sn.supplier_name, s.supplier_uid) || ' (' || n || ')', '; ' ORDER BY n DESC, s.supplier_uid)
             FILTER (WHERE rk <= 3) AS top_suppliers FROM (
        SELECT dept_key, supplier_uid, count(*) n,
               row_number() OVER (PARTITION BY dept_key ORDER BY count(*) DESC, supplier_uid) AS rk
        FROM d WHERE supplier_uid IS NOT NULL AND award_date >= DATE '{since}' GROUP BY 1, 2) s
      LEFT JOIN supplier_names sn USING (supplier_uid) GROUP BY 1),
    gaps AS (
      SELECT dept_key, median(gap) AS median_days_between_tenders FROM (
        SELECT dept_key, datediff('day', lag(publication_date) OVER (PARTITION BY dept_key ORDER BY publication_date),
                                  publication_date) AS gap
        FROM (SELECT DISTINCT dept_key, publication_date FROM t WHERE publication_date >= DATE '{since}'))
      WHERE gap IS NOT NULL GROUP BY 1),
    busy AS (
      SELECT dept_key, string_agg(m, ', ' ORDER BY n DESC, m) FILTER (WHERE rk <= 3) AS busiest_tender_months FROM (
        SELECT dept_key, strftime(publication_date, '%b') m, count(*) n,
               row_number() OVER (PARTITION BY dept_key ORDER BY count(*) DESC, strftime(publication_date, '%b')) rk
        FROM t WHERE publication_date >= DATE '{since}' GROUP BY 1, 2) GROUP BY 1),
    tstats AS (
      SELECT dept_key, count(*) AS n_tenders, count(*) FILTER (WHERE publication_date >= DATE '{since}') AS n_tenders_recent,
             count(*) FILTER (WHERE publication_date >= DATE '{since}' AND is_goods) AS n_goods_tenders_recent,
             max(publication_date) AS last_tender_date,
             median(datediff('day', publication_date, closing_date)) FILTER (WHERE closing_date >= publication_date)
               AS median_tender_open_days
      FROM t GROUP BY 1),
    lstats AS (SELECT dept_key, median(lead_days) AS median_notice_to_award_days, count(*) AS n_linked FROM leads GROUP BY 1),
    dstats AS (
      SELECT dept_key, count(*) AS n_deals, count(*) FILTER (WHERE award_date >= DATE '{since}') AS n_deals_recent,
             round(sum(value) FILTER (WHERE is_cad AND award_date >= DATE '{since}'), 0) AS value_recent,
             round(sum(value) FILTER (WHERE is_cad AND is_goods AND award_date >= DATE '{since}')
                   / nullif(sum(value) FILTER (WHERE is_cad AND award_date >= DATE '{since}'), 0), 3) AS goods_value_share,
             round(median(value) FILTER (WHERE is_cad AND value >= {MIN_VALUE} AND award_date >= DATE '{since}'), 0) AS deal_value_median,
             round(quantile_cont(value, 0.75) FILTER (WHERE is_cad AND value >= {MIN_VALUE} AND award_date >= DATE '{since}'), 0) AS deal_value_p75,
             round(max(value) FILTER (WHERE is_cad AND award_date >= DATE '{since}'), 0) AS deal_value_max,
             round(count(*) FILTER (WHERE competitive = 'non-competitive' AND award_date >= DATE '{since}')
                   / nullif(count(*) FILTER (WHERE competitive <> 'unknown' AND award_date >= DATE '{since}'), 0), 3)
               AS share_non_competitive,
             round(count(*) FILTER (WHERE buyer ILIKE '%public works%' OR buyer ILIKE '%(PSPC)%' OR buyer ILIKE '%procurement canada%')
                   / count(*), 3) AS share_bought_through_pspc,
             max(award_date) AS last_award_date
      FROM d GROUP BY 1)
    SELECT k.dept_key, coalesce(dn.dept_display, k.dept_key) AS buyer,
           ds.n_deals_recent, ds.value_recent, ds.goods_value_share, tsx.n_tenders_recent, tsx.n_goods_tenders_recent,
           round(tsx.n_tenders_recent / {months:.2f}, 2) AS tenders_per_month,
           g.median_days_between_tenders AS median_days_between_tender_days, b.busiest_tender_months, c.top_categories,
           ds.deal_value_median, ds.deal_value_p75, ds.deal_value_max,
           l.median_notice_to_award_days, l.n_linked AS notice_to_award_sample, tsx.median_tender_open_days,
           ds.share_non_competitive, ds.share_bought_through_pspc, s.top_suppliers,
           tsx.last_tender_date, ds.last_award_date, ds.n_deals AS n_deals_all_years, tsx.n_tenders AS n_tenders_all_years
    FROM (SELECT dept_key FROM dstats UNION SELECT dept_key FROM tstats) k
    LEFT JOIN dstats ds USING (dept_key) LEFT JOIN tstats tsx USING (dept_key) LEFT JOIN gaps g USING (dept_key)
    LEFT JOIN busy b USING (dept_key) LEFT JOIN cats c USING (dept_key) LEFT JOIN sup s USING (dept_key)
    LEFT JOIN lstats l USING (dept_key) LEFT JOIN dept_names dn USING (dept_key)
    WHERE coalesce(ds.n_deals, 0) + coalesce(tsx.n_tenders, 0) >= 3"""
    return _write_csv(con, sql, "value_recent DESC NULLS LAST, n_tenders_recent DESC NULLS LAST, dept_key", out)


def counts(con, out: Path) -> int:
    sql = """SELECT source, record_type, fiscal_year, count(*) AS lines, count(DISTINCT source_id) AS records,
                    max(first_seen) AS last_first_seen FROM lines GROUP BY ALL"""
    return _write_csv(con, sql, "source, record_type, fiscal_year", out)


def _write_csv(con, sql: str, order_by: str, out: Path) -> int:
    with common.atomic_target(out) as tmp:
        con.execute(f"COPY (SELECT * FROM ({sql}) ORDER BY {order_by}) TO '{tmp.as_posix()}' (HEADER, DELIMITER ',')")
        n = con.execute(f"SELECT count(*) FROM read_csv('{tmp.as_posix()}', all_varchar=true)").fetchone()[0]
    return n


def build(today: dt.date, outdir: Path | None = None) -> dict[str, int]:
    outdir = outdir or common.views_dir()
    con = duckdb.connect()
    con.execute("CREATE OR REPLACE MACRO first_part_s(s) AS nullif(trim(split_part(s, ';', 1)), '')")
    con.execute("""CREATE OR REPLACE MACRO fiscal_year_of(d) AS
                   CASE WHEN d IS NULL THEN 'undated'
                        WHEN month(d) >= 4 THEN CAST(year(d) AS VARCHAR) || '-' || CAST(year(d) + 1 AS VARCHAR)
                        ELSE CAST(year(d) - 1 AS VARCHAR) || '-' || CAST(year(d) AS VARCHAR) END""")
    setup(con, today)
    return {
        "retender_forecast": retender_forecast(con, today, outdir / "retender_forecast.csv"),
        "category_book": category_book(con, today, outdir / "category_book.csv"),
        "buyer_profiles": buyer_profiles(con, today, outdir / "buyer_profiles.csv"),
        "counts": counts(con, outdir / "counts.csv"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m herald.views", description=__doc__.split("\n\n")[0])
    ap.add_argument("--today", type=common.parse_date, help="build as of this date (default: today, UTC)")
    args = ap.parse_args(argv)
    today = args.today or common.today_utc()
    with common.run("views", {"today": today.isoformat()}) as ctx:
        res = build(today)
        ctx["counts"] = res
        ctx["rows"] = sum(res.values())
        ctx["notes"].append(", ".join(f"{k} {v} rows" for k, v in res.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
