"""Column specs for every stored table: (our name, source column, kind). Kinds and their Parquet types:

  str    VARCHAR   text as published, whitespace trimmed
  multi  VARCHAR   a CanadaBuys list cell ("*A\\n*B") stored as "A; B"
  date   DATE      first 10 characters as YYYY-MM-DD; anything else is NULL (counted in the run notes)
  ts     TIMESTAMP YYYY-MM-DDTHH:MM[:SS]
  float  DOUBLE    commas, spaces and $ dropped
  int    BIGINT

Every table also carries the provenance columns in PROVENANCE. Codes (GSIN, UNSPSC, reference numbers) stay text.
French columns are dropped except the title: the English side carries the same facts.
"""

from __future__ import annotations

import pyarrow as pa

KIND_TYPES = {"str": pa.string(), "multi": pa.string(), "date": pa.date32(), "ts": pa.timestamp("s"),
              "float": pa.float64(), "int": pa.int64()}

PROVENANCE = [
    ("fiscal_year", pa.string()),   # April-March fiscal year of the partition date, e.g. 2023-2024
    ("source_file", pa.string()),   # which published file the row came from
    ("row_hash", pa.string()),      # sha1 of the row's kept values: a changed row is a new version, never an overwrite
    ("first_seen", pa.date32()),    # the run date the row was first stored
]

_COMMON_HEAD = [
    ("reference_number", "referenceNumber-numeroReference", "str"),
    ("amendment_number", "amendmentNumber-numeroModification", "str"),
]
_CODES = [
    ("gsin", "gsin-nibs", "multi"),
    ("gsin_description", "gsinDescription-nibsDescription-eng", "multi"),
    ("unspsc", "unspsc", "multi"),
    ("unspsc_description", "unspscDescription-eng", "multi"),
    ("category", "procurementCategory-categorieApprovisionnement", "multi"),
    ("notice_type", "noticeType-avisType-eng", "str"),
    ("method", "procurementMethod-methodeApprovisionnement-eng", "str"),
    ("selection_criteria", "selectionCriteria-criteresSelection-eng", "str"),
    ("limited_tendering_reason", "limitedTenderingReason-raisonAppelOffresLimite-eng", "multi"),
    ("trade_agreements", "tradeAgreements-accordsCommerciaux-eng", "multi"),
]
_CONTACT = [
    ("contact_name", "contactInfoName-informationsContactNom", "str"),
    ("contact_email", "contactInfoEmail-informationsContactCourriel", "str"),
    ("contact_phone", "contactInfoPhone-contactInfoTelephone", "str"),
]

CANADABUYS = {
    "tenders": _COMMON_HEAD + [
        ("solicitation_number", "solicitationNumber-numeroSollicitation", "str"),
        ("title", "title-titre-eng", "str"),
        ("title_fr", "title-titre-fra", "str"),
        ("publication_date", "publicationDate-datePublication", "date"),
        ("closing_at", "tenderClosingDate-appelOffresDateCloture", "ts"),
        ("amendment_date", "amendmentDate-dateModification", "date"),
        ("expected_start_date", "expectedContractStartDate-dateDebutContratPrevue", "date"),
        ("expected_end_date", "expectedContractEndDate-dateFinContratPrevue", "date"),
        ("status", "tenderStatus-appelOffresStatut-eng", "str"),
    ] + _CODES + [
        ("regions_of_opportunity", "regionsOfOpportunity-regionAppelOffres-eng", "multi"),
        ("regions_of_delivery", "regionsOfDelivery-regionsLivraison-eng", "multi"),
        ("buyer", "contractingEntityName-nomEntitContractante-eng", "str"),
        ("buyer_city", "contractingEntityAddressCity-entiteContractanteAdresseVille-eng", "str"),
        ("buyer_province", "contractingEntityAddressProvince-entiteContractanteAdresseProvince-eng", "str"),
        ("end_user", "endUserEntitiesName-nomEntitesUtilisateurFinal-eng", "multi"),
    ] + _CONTACT + [
        ("notice_url", "noticeURL-URLavis-eng", "str"),
        ("attachments", "attachment-piecesJointes-eng", "multi"),
        ("description", "tenderDescription-descriptionAppelOffres-eng", "str"),
    ],
    "awards": _COMMON_HEAD + [
        ("solicitation_number", "solicitationNumber-numeroSollicitation", "str"),
        ("contract_number", "contractNumber-numeroContrat", "str"),
        ("title", "title-titre-eng", "str"),
        ("title_fr", "title-titre-fra", "str"),
        ("publication_date", "publicationDate-datePublication", "date"),
        ("award_date", "contractAwardDate-dateAttributionContrat", "date"),
        ("amendment_date", "amendmentDate-dateModification", "date"),
        ("start_date", "contractStartDate-contratDateDebut", "date"),
        ("end_date", "contractEndDate-dateFinContrat", "date"),
        ("contract_amount", "contractAmount-montantContrat", "float"),
        ("total_contract_value", "totalContractValue-valeurTotaleContrat", "float"),
        ("currency", "contractCurrency-contratMonnaie", "str"),
        ("status", "awardStatus-attributionStatut-eng", "str"),
        ("instrument_type", "instrumentType-typeInstrument-eng", "str"),
        ("amendment_type", "amendmentType-typeModification-eng", "str"),
    ] + _CODES + [
        ("regions_of_delivery", "regionsOfDelivery-regionsLivraison-eng", "multi"),
        ("supplier_legal_name", "supplierLegalName-nomLegalFournisseur-eng", "str"),
        ("supplier_city", "supplierAddressCity-fournisseurAdresseVille-eng", "str"),
        ("supplier_province", "supplierAddressProvince-fournisseurAdresseProvince-eng", "str"),
        ("supplier_postal_code", "supplierAddressPostalCode-fournisseurAdresseCodePostal", "str"),
        ("supplier_country", "supplierAddressCountry-fournisseurAdressePays-eng", "str"),
        ("buyer", "contractingEntityName-nomEntitContractante-eng", "str"),
        ("buyer_city", "contractingEntityAddressCity-entiteContractanteAdresseVille-eng", "str"),
        ("buyer_province", "contractingEntityAddressProvince-entiteContractanteAdresseProvince-eng", "str"),
        ("end_user", "endUserEntitiesName-nomEntitesUtilisateurFinal-eng", "multi"),
    ] + _CONTACT + [
        ("description", "awardDescription-descriptionAttribution-eng", "str"),
    ],
    "contracts": _COMMON_HEAD + [
        ("procurement_number", "procurementNumber-numeroApprovisionnement", "str"),
        ("solicitation_number", "solicitationNumber-numeroSollicitation", "str"),
        ("contract_number", "contractNumber-numeroContrat", "str"),
        ("number_of_records", "numberOfRecords-nombreEnregistrements", "int"),
        ("title", "title-titre-eng", "str"),
        ("title_fr", "title-titre-fra", "str"),
        ("publication_date", "publicationDate-datePublication", "date"),
        ("award_date", "contractAwardDate-dateAttributionContrat", "date"),
        ("amendment_date", "amendmentDate-dateModification", "date"),
        ("start_date", "contractStartDate-contratDateDebut", "date"),
        ("end_date", "contractEndDate-dateFinContrat", "date"),
        ("contract_amount", "contractAmount-montantContrat", "float"),
        ("total_contract_value", "totalContractValue-valeurTotaleContrat", "float"),
        ("currency", "contractCurrency-contratMonnaie", "str"),
        ("status", "contractStatus-statutContrat-eng", "str"),
        ("instrument_type", "instrumentType-typeInstrument-eng", "str"),
        ("amendment_type", "amendmentType-typeModification-eng", "str"),
    ] + _CODES + [
        ("regions_of_delivery", "regionsOfDelivery-regionsLivraison-eng", "multi"),
        ("supplier_legal_name", "supplierLegalName-nomLegalFournisseur-eng", "str"),
        ("supplier_standardized_name", "supplierStandardizedName-nomNormaliseFournisseur-eng", "str"),
        ("supplier_operating_name", "supplierOperatingName-nomCommercialFournisseur-eng", "str"),
        ("supplier_employee_count", "supplierEmployeeCount-fournisseurNombreEmployes-eng", "str"),
        ("supplier_city", "supplierAddressCity-fournisseurAdresseVille-eng", "str"),
        ("supplier_province", "supplierAddressProvince-fournisseurAdresseProvince-eng", "str"),
        ("supplier_postal_code", "supplierAddressPostalCode-fournisseurAdresseCodePostal", "str"),
        ("supplier_country", "supplierAddressCountry-fournisseurAdressePays-eng", "str"),
        ("buyer", "contractingEntityName-nomEntitContractante-eng", "str"),
        ("buyer_province", "contractingEntityAddressProvince-entiteContractanteAdresseProvince-eng", "str"),
        ("end_user", "endUserEntitiesName-nomEntitesUtilisateurFinal-eng", "multi"),
        ("end_user_office", "endUserEntitiesOfficeName-bureauNomEntitesUtilisateurFinal-eng", "str"),
    ] + _CONTACT + [
        ("pct_goods_by_country", "percentageOfGoodsByCountry-pourcentageDeBiensParPays", "multi"),
        ("description", "tenderDescription-descriptionAppelOffres-eng", "str"),
    ],
}

# The date that decides a row's fiscal-year partition, in order of preference.
CANADABUYS_PARTITION_DATE = {
    "tenders": ("publication_date", "amendment_date"),
    "awards": ("publication_date", "award_date", "amendment_date"),
    # the legacy contract file has no publication dates, and its amendment rows carry only an amendment date
    "contracts": ("award_date", "publication_date", "amendment_date"),
}

TORONTO = {
    "solicitations": [
        ("document_number", "Document Number", "str"),
        ("rfx_type", "RFx (Solicitation) Type", "str"),
        ("noip_type", "NOIP (Notice of Intended Procurement) Type", "str"),
        ("issue_date", "Issue Date", "date"),
        ("submission_deadline", "Submission Deadline", "date"),
        ("category", "High Level Category", "str"),
        ("description", "Solicitation Document Description", "str"),
        ("division", "Division", "str"),
        ("buyer_name", "Buyer Name", "str"),
        ("buyer_email", "Buyer Email", "str"),
        ("buyer_phone", "Buyer Phone Number", "str"),
        ("wards", "Wards", "str"),
    ],
    # One row per (document, awarded supplier): the file repeats each document's Award list on every row.
    "awards": [
        ("document_number", "Document Number", "str"),
        ("rfx_type", "RFx (Solicitation) Type", "str"),
        ("category", "High Level Category", "str"),
        ("award_authority_date", "Award Authority Obtained Date", "date"),
        ("division", "Division", "str"),
        ("buyer_name", "Buyer Name", "str"),
        ("buyer_email", "Buyer Email", "str"),
        ("description", "Solicitation Document Description", "str"),
        ("wards", "Wards", "str"),
        ("supplier", "Successful_Bidder", "str"),
        ("award_amount", "Award_Amount", "float"),
        ("initial_contract_value", "Initial_Contract_Val", "float"),
        ("date_awarded", "Date_Awarded", "date"),
        ("cancellation_date", "Cancellation_Date", "date"),
        ("supplier_city", "city", "str"),
        ("supplier_province", "province", "str"),
        ("supplier_postal_code", "postalCode", "str"),
        ("supplier_country", "country", "str"),
    ],
}
TORONTO_PARTITION_DATE = {"solicitations": ("issue_date",), "awards": ("date_awarded", "award_authority_date")}


def arrow_schema(spec: list[tuple[str, str, str]]) -> pa.Schema:
    return pa.schema([(name, KIND_TYPES[kind]) for name, _src, kind in spec] + PROVENANCE)
