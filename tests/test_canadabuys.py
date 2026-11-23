import datetime as dt
import hashlib
from unittest import mock

import duckdb

from collectors import canadabuys, common
from herald import store
from tests.helpers import FIXTURES, TempDataCase

FILES = ["--files", str(FIXTURES / "canadabuys")]


def sha(paths):
    h = hashlib.sha1()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()


class CanadaBuysTest(TempDataCase):
    def rows(self, table, where="true"):
        files = store.parquet_files(self.data / "canadabuys" / table)
        return duckdb.sql(f"SELECT * FROM read_parquet({store.sql_list(files)}, union_by_name=true) WHERE {where}").fetchall()

    def test_backfill_counts_types_and_partitions(self):
        canadabuys.main(["--backfill"] + FILES)
        self.assertEqual(len(self.rows("tenders")), 7)
        self.assertEqual(len(self.rows("contracts")), 10)
        self.assertEqual(len(self.rows("awards")), 3)
        self.assertTrue((self.data / "canadabuys/tenders/2019-2020/base.parquet").exists())
        con = duckdb.connect()
        f = store.parquet_files(self.data / "canadabuys" / "tenders")
        r = con.execute(f"""SELECT publication_date, closing_at, regions_of_delivery, gsin, category, description
                            FROM read_parquet({store.sql_list(f)}) WHERE solicitation_number = '21120-000001'""").fetchone()
        self.assertEqual(r[0], dt.date(2019, 5, 3))
        self.assertEqual(r[1], dt.datetime(2019, 6, 1, 14, 0))
        self.assertEqual(r[2], "Ontario (except NCR); Quebec (except NCR)")
        self.assertEqual((r[3], r[4]), ("N7110", "GD"))
        self.assertIn("\n", r[5])          # descriptions keep their line breaks
        types = dict(con.execute(f"DESCRIBE SELECT * FROM read_parquet({store.sql_list(f)})").fetchall() and
                     [(c[0], c[1]) for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet({store.sql_list(f)})").fetchall()])
        self.assertEqual(types["publication_date"], "DATE")
        self.assertEqual(types["gsin"], "VARCHAR")
        # amendment rows with only an amendment date land in that date's fiscal year, not 'undated'
        self.assertFalse((self.data / "canadabuys/contracts/undated").exists())

    def test_backfill_is_idempotent(self):
        canadabuys.main(["--backfill"] + FILES)
        before = sha(store.parquet_files(self.data / "canadabuys"))
        canadabuys.main(["--backfill"] + FILES)
        self.assertEqual(before, sha(store.parquet_files(self.data / "canadabuys")))

    def test_backfill_one_fiscal_year(self):
        canadabuys.main(["--backfill", "--fy", "2020-2021", "--table", "tenders"] + FILES)
        dirs = sorted(p.name for p in (self.data / "canadabuys/tenders").iterdir())
        self.assertEqual(dirs, ["2020-2021"])

    def test_daily_keeps_only_new_or_changed_rows(self):
        canadabuys.main(["--backfill"] + FILES)
        canadabuys.main(["--date", "2026-11-23"] + FILES)
        daily = self.data / "canadabuys/tenders/daily/2026-11-23.parquet"
        got = duckdb.sql(f"SELECT solicitation_number, first_seen FROM read_parquet('{daily}')").fetchall()
        self.assertEqual(got, [("21120-000009", dt.date(2026, 11, 23))])   # the reordered list cell is not a change
        awards = duckdb.sql(f"SELECT status FROM read_parquet('{self.data}/canadabuys/awards/daily/2026-11-23.parquet')").fetchall()
        self.assertEqual(awards, [("Expired",)])                            # a status change is a new version
        self.assertFalse((self.data / "canadabuys/contracts/daily/2026-11-23.parquet").exists())
        self.assertEqual(len(self.rows("awards")), 4)                       # the old version is kept
        before = sha([daily])
        canadabuys.main(["--date", "2026-11-23"] + FILES)                   # same day again: same file
        self.assertEqual(before, sha([daily]))
        runs = common.last_runs("canadabuys")
        self.assertEqual(runs[-1]["status"], "ok")
        self.assertEqual(runs[-1]["counts"]["written"], {"tenders": 1, "awards": 1, "contracts": 0})

    def test_compaction_moves_daily_rows_into_monthly_files(self):
        canadabuys.main(["--backfill"] + FILES)
        canadabuys.main(["--date", "2026-10-30"] + FILES)
        n = len(self.rows("tenders"))
        from herald import compact
        compact.main(["--before", "2026-11-01"])
        self.assertFalse(list((self.data / "canadabuys/tenders/daily").glob("*.parquet")))
        m = self.data / "canadabuys/tenders/2026-2027/m-2026-10.parquet"
        self.assertTrue(m.exists())
        self.assertEqual(len(self.rows("tenders")), n)
        first_seen = duckdb.sql(f"SELECT first_seen FROM read_parquet('{m}')").fetchall()
        self.assertEqual(first_seen, [(dt.date(2026, 10, 30),)])

    def test_rebuilding_a_base_drops_rows_now_in_base_from_daily_files(self):
        canadabuys.main(["--backfill"] + FILES)
        canadabuys.main(["--date", "2026-11-23"] + FILES)
        canadabuys.main(["--backfill", "--table", "tenders"] + FILES)       # base unchanged: daily row stays
        self.assertEqual(len(self.rows("tenders")), 8)

    def test_size_cap_splits_files(self):
        canadabuys.main(["--backfill", "--table", "contracts"] + FILES)
        con = duckdb.connect()
        src = store.parquet_files(self.data / "canadabuys/contracts")
        target = self.tmp / "split" / "base.parquet"
        whole = store.write_capped(con, f"SELECT * FROM read_parquet({store.sql_list(src)}, union_by_name=true)",
                                   self.tmp / "whole" / "base.parquet", "reference_number, amendment_number")
        size = whole[0].stat().st_size
        with mock.patch.object(common, "MAX_FILE_BYTES", size - 1), \
                mock.patch.object(common, "SPLIT_TARGET_BYTES", size // 3):
            files = store.write_capped(con, f"SELECT * FROM read_parquet({store.sql_list(src)}, union_by_name=true)",
                                       target, "reference_number, amendment_number")
        self.assertGreater(len(files), 1)
        self.assertTrue(all(f.name.startswith("base-") for f in files))
        total = con.execute(f"SELECT count(*) FROM read_parquet({store.sql_list(files)})").fetchone()[0]
        self.assertEqual(total, 10)

    def test_missing_daily_file_is_partial_not_fatal(self):
        canadabuys.main(["--date", "2027-06-15", "--table", "awards"] + FILES)   # 2027-2028 file is not in fixtures
        self.assertEqual(common.last_runs("canadabuys")[-1]["status"], "partial")


class HelpersTest(TempDataCase):
    def test_fiscal_year(self):
        self.assertEqual(common.fiscal_year(dt.date(2026, 3, 31)), "2025-2026")
        self.assertEqual(common.fiscal_year(dt.date(2026, 4, 1)), "2026-2027")
        self.assertEqual(common.fiscal_year(None), "undated")

    def test_convert(self):
        from collections import Counter
        bad = Counter()
        self.assertEqual(store.convert("*A\n*B\n", "multi", bad, "c"), "A; B")
        self.assertEqual(store.convert(" 1,234.50 ", "float", bad, "c"), 1234.5)
        self.assertIsNone(store.convert("not a date", "date", bad, "d"))
        self.assertEqual(bad["d"], 1)

    def test_row_hash_ignores_list_order_only(self):
        a = store.row_hash(["x", "A; B"], ["str", "multi"])
        self.assertEqual(a, store.row_hash(["x", "B; A"], ["str", "multi"]))
        self.assertNotEqual(a, store.row_hash(["x", "A; C"], ["str", "multi"]))
        self.assertNotEqual(a, store.row_hash(["y", "A; B"], ["str", "multi"]))
