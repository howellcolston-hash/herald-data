# City of Toronto solicitations

- **Publisher:** City of Toronto, Purchasing and Materials Management (Toronto Bids), on Toronto Open Data (ckan0.cf.opendata.inter.prod-toronto.ca).
- **Licence:** Open Government Licence - Toronto (https://open.toronto.ca/open-data-license/).
- **Collector:** `python -m collectors.toronto`. Storage: `data/toronto/solicitations/`.
- **Dataset:** `tobids-all-open-solicitations` ("Toronto Bids Solicitations"), resource `all-solicitations.csv`. Refreshed daily.
- **Coverage:** 855 solicitations in the 2026-11-21 file, mostly 2022 on, a few back to 2008. One row per solicitation document.
- **Known artifacts:** no commodity codes (only a high-level category: Goods and Services, Construction Services, Professional Services); the buyer is always the City (the division is stored as the end user); one row in the 2026-11 file has no document number. The file may drop closed solicitations, so the daily increments are what keeps them.
- **Backfill:** only what the current file holds (`--backfill`).
