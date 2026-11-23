import csv
import datetime as dt

import duckdb

from collectors import canadabuys, toronto
from herald import lines, store, views
from tests.helpers import FIXTURES, TempDataCase

TODAY = dt.date(2026, 11, 23)


class LinesAndViewsTest(TempDataCase):
    def setUp(self):
        super().setUp()
        canadabuys.main(["--backfill", "--files", str(FIXTURES / "canadabuys")])
        canadabuys.main(["--date", TODAY.isoformat(), "--files", str(FIXTURES / "canadabuys")])
        toronto.main(["--backfill", "--files", str(FIXTURES / "toronto")])
        lines.build()
        self.res = views.build(TODAY)

    def read(self, name):
        with open(self.tmp / "views" / f"{name}.csv", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_lines_mirror_every_stored_row(self):
        stored = sum(store.count_rows(duckdb.connect(), store.table_root(s, t))
                     for s, t in [("canadabuys", "tenders"), ("canadabuys", "awards"), ("canadabuys", "contracts"),
                                  ("toronto", "solicitations"), ("toronto", "awards")])
        lfiles = store.parquet_files(self.data / "lines")
        n = duckdb.sql(f"SELECT count(*) FROM read_parquet({store.sql_list(lfiles)}, union_by_name=true)").fetchall()[0][0]
        self.assertEqual(n, stored)
        again = lines.build()
        self.assertEqual(again["built"], 0)

    def test_lines_keys(self):
        lfiles = store.parquet_files(self.data / "lines")
        con = duckdb.connect()
        rel = f"read_parquet({store.sql_list(lfiles)}, union_by_name=true)"
        r = con.execute(f"SELECT buyer_key, end_user_key, gsin_class, is_goods, competitive, supplier_key FROM {rel} "
                        "WHERE record_type = 'contract' AND source_id = '21120-000006/001/PR' AND amendment = '001'").fetchone()
        self.assertEqual(r, ("PUBLIC WORKS AND GOVERNMENT SERVICES", "CORRECTIONAL SERVICE", "N7110", True,
                             "competitive", "ACME FURNITURE"))

    def test_retender_forecast(self):
        rows = self.read("retender_forecast")
        self.assertEqual(len(rows), 2, rows)          # contract 6 and the DND goods award; not the twin, services or terminated
        c6 = next(r for r in rows if r["contract_number"] == "21120-000006/001/PR")
        self.assertEqual(c6["end_date"], "2027-03-31")
        self.assertEqual(float(c6["value"]), 300000.0)
        self.assertEqual(c6["buyer"], "Correctional Service of Canada")
        self.assertEqual(c6["incumbent"], "ACME FURNITURE")
        self.assertEqual(c6["window_basis"], "department")
        self.assertEqual(c6["original_tender_date"], "2024-05-03")
        self.assertTrue(c6["earlier_tender_dates"].startswith("2024-05-03; 2023-05-03; 2022-05-03"))
        lead = 60  # every fixture contract was awarded 60 days after its tender
        self.assertEqual(float(c6["typical_notice_to_award_days"]), lead)
        self.assertEqual(c6["expected_notice_from"], (dt.date(2027, 3, 31) - dt.timedelta(days=lead)).isoformat())
        self.assertEqual(c6["notice_status"], "upcoming")
        self.assertEqual(c6["possible_replacement_tender"][:14], "PW-26-00000009")
        dnd = next(r for r in rows if r["source_id"] == "MX-0000000002")
        self.assertEqual(dnd["incumbent"], "ACME FURNITURE")   # the legal-name-only award joins the standardized supplier
        self.assertEqual([r["expected_notice_from"] for r in rows], sorted(r["expected_notice_from"] for r in rows))

    def test_category_book_and_buyer_profiles(self):
        book = {(r["scheme"], r["class"]): r for r in self.read("category_book")}
        n7110 = book[("GSIN", "N7110")]
        self.assertEqual(n7110["description"], "Office Furniture")
        self.assertEqual(int(n7110["distinct_winners"]), 2)   # Acme (two spellings) and Delta; Gamma ended
        self.assertEqual(float(n7110["share_non_competitive"]), 0.0)
        self.assertTrue(n7110["top_winners"].startswith("ACME FURNITURE (7)"), n7110["top_winners"])   # 6 contracts + 1 award
        profiles = {r["dept_key"]: r for r in self.read("buyer_profiles")}
        csc = profiles["CORRECTIONAL SERVICE"]
        self.assertEqual(float(csc["median_notice_to_award_days"]), 60.0)
        self.assertEqual(float(csc["share_bought_through_pspc"]), 1.0)
        counts = self.read("counts")
        self.assertIn("toronto", {r["source"] for r in counts})
