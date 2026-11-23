import duckdb

from collectors import toronto
from herald import store
from tests.helpers import FIXTURES, TempDataCase


class TorontoTest(TempDataCase):
    def test_backfill_explodes_award_lists_once(self):
        toronto.main(["--backfill", "--files", str(FIXTURES / "toronto")])
        files = store.parquet_files(self.data / "toronto" / "awards")
        rows = duckdb.sql(f"SELECT supplier, award_amount, fiscal_year FROM read_parquet({store.sql_list(files)}) "
                          "ORDER BY supplier").fetchall()
        self.assertEqual(rows, [("ASCA Office Solutions", 771931.57, "2012-2013"),
                                ("Computer Media Group", 26773.58, "2012-2013")])
        sol = store.parquet_files(self.data / "toronto" / "solicitations")
        self.assertEqual(duckdb.sql(f"SELECT count(*) FROM read_parquet({store.sql_list(sol)})").fetchall()[0][0], 1)

    def test_daily_after_backfill_adds_nothing(self):
        toronto.main(["--backfill", "--files", str(FIXTURES / "toronto")])
        toronto.main(["--date", "2026-11-23", "--files", str(FIXTURES / "toronto")])
        self.assertFalse((self.data / "toronto/awards/daily").exists() and
                         list((self.data / "toronto/awards/daily").glob("*.parquet")))
