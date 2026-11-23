# City of Toronto awarded contracts

- **Publisher:** City of Toronto, Purchasing and Materials Management (Toronto Bids), on Toronto Open Data (ckan0.cf.opendata.inter.prod-toronto.ca).
- **Licence:** Open Government Licence - Toronto (https://open.toronto.ca/open-data-license/).
- **Collector:** `python -m collectors.toronto`. Storage: `data/toronto/awards/`.
- **Dataset:** `tobids-awarded-contracts` ("Toronto Bids Awarded Contracts"), resource `awarded-contracts.csv`. Refreshed daily.
- **Coverage:** 7,840 rows in the 2026-11-20 file, 6,507 documents, 2012 on.
- **Row:** one (document, awarded supplier, amount, date). The file repeats each document's whole `Award` JSON list on every row; the collector reads the list once per document.
- **Known artifacts:** about 40 award amounts are not numbers and are stored as NULL; no commodity codes; supplier addresses are often blank. The file has no stable row id: a row the City later corrects is stored as a second row beside the first.
- **Backfill:** only what the current file holds.
