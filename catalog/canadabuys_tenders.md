# CanadaBuys tender notices

- **Publisher:** Public Services and Procurement Canada (PSPC), CanadaBuys open data, on open.canada.ca.
- **Licence:** Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada). Attribution: "Contains information licensed under the Open Government Licence - Canada."
- **Format:** UTF-8 CSV with a BOM, bilingual column names (`english-french`), list cells written as `*A` lines. French columns are not stored except the title.
- **Collector:** `python -m collectors.canadabuys` (docstring lists every mode). Storage: `data/canadabuys/tenders/` (layout in README.md).
- **Package:** 6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2 ("CanadaBuys tender notices").
- **Files read:** backfill: `2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv` (legacy Buyandsell notices, 2009 to 2022-08) and `tenderNoticeComplete-avisAppelOffresComplet.csv` (every CanadaBuys notice since 2022-08-08). Daily: `newTenderNotice-nouvelAvisAppelOffres.csv` (notices published that day), `openTenderNotice-ouvertAvisAppelOffres.csv` (open notices with their amendments) and the current fiscal year's `<fy>-TenderNotice-AvisAppelOffres.csv`; Sundays also the complete file.
- **Cadence and lag:** the new-notice file is refreshed during the day; the complete and fiscal-year files once a day (about 11:00-13:00 UTC). The daily run is at 14:37 UTC.
- **Coverage:** federal notices published on Buyandsell/CanadaBuys, plus the provincial, municipal and MASH notices that CanadaBuys carries since 2022 (they show as the contracting entity). 102,794 rows in the 2026-11-22 files (71,310 legacy, 31,484 complete), one row per notice amendment.
- **Row:** one notice amendment (`reference_number`, `amendment_number`). A row the publisher changes later is stored again with a new `row_hash`; the old one stays.
- **Known artifacts:** legacy notices have GSIN codes and no UNSPSC; CanadaBuys notices mostly UNSPSC and no GSIN. `end_user` is often blank for non-PSPC buyers. Legacy notices have no notice URL. Partition date is the publication date.
- **Backfill:** yes, complete from 2009 (`--backfill`, by fiscal year with `--fy`).
