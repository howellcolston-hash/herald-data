# CanadaBuys award notices

- **Publisher:** Public Services and Procurement Canada (PSPC), CanadaBuys open data, on open.canada.ca.
- **Licence:** Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada). Attribution: "Contains information licensed under the Open Government Licence - Canada."
- **Format:** UTF-8 CSV with a BOM, bilingual column names (`english-french`), list cells written as `*A` lines. French columns are not stored except the title.
- **Collector:** `python -m collectors.canadabuys` (docstring lists every mode). Storage: `data/canadabuys/awards/` (layout in README.md).
- **Package:** a1acb126-9ce8-40a9-b889-5da2b1dd20cb ("CanadaBuys award notices").
- **Files read:** backfill: `2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv` (2012 to 2022-08) and `awardNoticeComplete-avisAttributionComplet.csv` (since 2022-08-08). Daily: the current fiscal year's `<fy>-awardNotice-avisAttribution.csv`; Sundays also the complete file.
- **Cadence and lag:** daily file refresh; award notices are published days to weeks after the award.
- **Coverage:** published award notices from federal and other CanadaBuys buyers: 135,946 rows in the 2026-11-22 files (106,416 legacy, 29,530 complete).
- **Row:** one award notice amendment. Values: `contract_amount` (this notice's amount) and `total_contract_value` (often 0 in CanadaBuys notices); currency is mostly CAD, with USD, EUR and others in the legacy file.
- **Known artifacts:** many CanadaBuys award notices have no contract number (the reference number `MX-...` identifies them); legacy notices carry `W8484-127434:001:EEM`-style references, read as `/`. Many awards repeat a contract-history record (about 109,000 by contract number); the views keep the contract-history copy. Supplier names are legal names only (no standardized name).
- **Backfill:** yes, from 2012.
