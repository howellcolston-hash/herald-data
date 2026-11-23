# CanadaBuys contract history

- **Publisher:** Public Services and Procurement Canada (PSPC), CanadaBuys open data, on open.canada.ca.
- **Licence:** Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada). Attribution: "Contains information licensed under the Open Government Licence - Canada."
- **Format:** UTF-8 CSV with a BOM, bilingual column names (`english-french`), list cells written as `*A` lines. French columns are not stored except the title.
- **Collector:** `python -m collectors.canadabuys` (docstring lists every mode). Storage: `data/canadabuys/contracts/` (layout in README.md).
- **Package:** 4fe645a1-ffcd-40c1-9385-2c771be956a4 ("CanadaBuys contract history").
- **Files read:** backfill: `2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv` (2009-01 to 2023-05) and `contractHistoryComplete-contratsOctroyesComplet.csv` (since 2023-06-01). Daily: the current fiscal year's `<fy>-contractHistory-contratsOctroyes.csv`; Sundays also the complete file.
- **Cadence and lag:** the contract files were last refreshed 2026-10-28 when checked on 2026-11-22: expect roughly monthly refreshes.
- **Coverage:** contracts and amendments awarded by PSPC (Public Works and Government Services Canada) on behalf of departments: 510,250 rows in the 2026-10-28 files (486,336 legacy, 23,914 complete).
- **Row:** one contract amendment (`reference_number` is the contract number, `amendment_number` 000 is the original). `supplier_standardized_name` is PSPC's standardized supplier name, used first for matching.
- **Known artifacts:** the legacy file has no publication dates, and its amendment rows have no award date: those rows are partitioned by their amendment date. Some end dates are typos (years like 3009); the views ignore end dates outside 1990-2099. `instrument_type` (Contract, Standing Offer, Supply Arrangement, ...) is blank in most legacy rows. The contracting entity is always PSPC; the department is in `end_user`.
- **Backfill:** yes, from 2009-01.
