"""Writes the small synthetic CanadaBuys and Toronto fixtures the tests read (run once; the CSVs are committed).

    python tests/fixtures/make_fixtures.py

The headers are the publisher's real column names (copied from the 2026-11 files); the rows are invented. The
scenario, as of TODAY = 2026-11-23:
  * Correctional Service of Canada (bought through PSPC) tenders office furniture (GSIN N7110) every year; six past
    tenders link to six contracts by solicitation number, each awarded about 60 days after its tender.
  * Contract 21120-000006/001/PR (Acme Furniture) ends 2027-03-31 after amendment 001 extended it: it is the
    re-tender forecast's goods line. Its award notice twin (same contract number) must be dropped as a duplicate.
  * A DND services contract ends in 2027 too and must stay out of the forecast (not goods).
  * A cancelled goods contract ending in 2027 must stay out.
  * The award "Acme Furniture Limited" (legal name only) must join supplier key ACME FURNITURE.
  * The daily files repeat the complete files, reorder a list cell (no new version), change one award's status (a
    new version) and add one new tender.
"""

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEADERS = {
 "tenders": [
  "title-titre-eng",
  "title-titre-fra",
  "referenceNumber-numeroReference",
  "amendmentNumber-numeroModification",
  "solicitationNumber-numeroSollicitation",
  "publicationDate-datePublication",
  "tenderClosingDate-appelOffresDateCloture",
  "amendmentDate-dateModification",
  "expectedContractStartDate-dateDebutContratPrevue",
  "expectedContractEndDate-dateFinContratPrevue",
  "tenderStatus-appelOffresStatut-eng",
  "tenderStatus-appelOffresStatut-fra",
  "gsin-nibs",
  "gsinDescription-nibsDescription-eng",
  "gsinDescription-nibsDescription-fra",
  "unspsc",
  "unspscDescription-eng",
  "unspscDescription-fra",
  "procurementCategory-categorieApprovisionnement",
  "noticeType-avisType-eng",
  "noticeType-avisType-fra",
  "procurementMethod-methodeApprovisionnement-eng",
  "procurementMethod-methodeApprovisionnement-fra",
  "selectionCriteria-criteresSelection-eng",
  "selectionCriteria-criteresSelection-fra",
  "limitedTenderingReason-raisonAppelOffresLimite-eng",
  "limitedTenderingReason-raisonAppelOffresLimite-fra",
  "tradeAgreements-accordsCommerciaux-eng",
  "tradeAgreements-accordsCommerciaux-fra",
  "regionsOfOpportunity-regionAppelOffres-eng",
  "regionsOfOpportunity-regionAppelOffres-fra",
  "regionsOfDelivery-regionsLivraison-eng",
  "regionsOfDelivery-regionsLivraison-fra",
  "contractingEntityName-nomEntitContractante-eng",
  "contractingEntityAddressLine-ligneAdresseEntiteContractante-eng",
  "contractingEntityAddressCity-entiteContractanteAdresseVille-eng",
  "contractingEntityAddressProvince-entiteContractanteAdresseProvince-eng",
  "contractingEntityAddressPostalCode-entiteContractanteAdresseCodePostal",
  "contractingEntityAddressCountry-entiteContractanteAdressePays-eng",
  "contractingEntityName-nomEntitContractante-fra",
  "contractingEntityAddressLine-ligneAdresseEntiteContractante-fra",
  "contractingEntityAddressCity-entiteContractanteAdresseVille-fra",
  "contractingEntityAddressProvince-entiteContractanteAdresseProvince-fra",
  "contractingEntityAddressCountry-entiteContractanteAdressePays-fra",
  "endUserEntitiesName-nomEntitesUtilisateurFinal-eng",
  "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-eng",
  "endUserEntitiesName-nomEntitesUtilisateurFinal-fra",
  "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-fra",
  "contactInfoName-informationsContactNom",
  "contactInfoEmail-informationsContactCourriel",
  "contactInfoPhone-contactInfoTelephone",
  "contactInfoFax",
  "contactInfoAddressLine-contactInfoAdresseLigne-eng",
  "contactInfoCity-contacterInfoVille-eng",
  "contactInfoProvince-contacterInfoProvince-eng",
  "contactInfoPostalcode",
  "contactInfoCountry-contactInfoPays-eng",
  "contactInfoAddressLine-contactInfoAdresseLigne-fra",
  "contactInfoCity-contacterInfoVille-fra",
  "contactInfoProvince-contacterInfoProvince-fra",
  "contactInfoCountry-contactInfoPays-fra",
  "noticeURL-URLavis-eng",
  "noticeURL-URLavis-fra",
  "attachment-piecesJointes-eng",
  "attachment-piecesJointes-fra",
  "tenderDescription-descriptionAppelOffres-eng",
  "tenderDescription-descriptionAppelOffres-fra"
 ],
 "awards": [
  "title-titre-eng",
  "title-titre-fra",
  "referenceNumber-numeroReference",
  "amendmentNumber-numeroModification",
  "solicitationNumber-numeroSollicitation",
  "contractNumber-numeroContrat",
  "publicationDate-datePublication",
  "contractAwardDate-dateAttributionContrat",
  "amendmentDate-dateModification",
  "contractStartDate-contratDateDebut",
  "contractEndDate-dateFinContrat",
  "contractAmount-montantContrat",
  "totalContractValue-valeurTotaleContrat",
  "contractCurrency-contratMonnaie",
  "awardStatus-attributionStatut-eng",
  "awardStatus-attributionStatut-fra",
  "instrumentType-typeInstrument-eng",
  "instrumentType-typeInstrument-fra",
  "amendmentType-typeModification-eng",
  "amendmentType-typeModification-fra",
  "gsin-nibs",
  "gsinDescription-nibsDescription-eng",
  "gsinDescription-nibsDescription-fra",
  "unspsc",
  "unspscDescription-eng",
  "unspscDescription-fra",
  "procurementCategory-categorieApprovisionnement",
  "noticeType-avisType-eng",
  "noticeType-avisType-fra",
  "procurementMethod-methodeApprovisionnement-eng",
  "procurementMethod-methodeApprovisionnement-fra",
  "selectionCriteria-criteresSelection-eng",
  "selectionCriteria-criteresSelection-fra",
  "limitedTenderingReason-raisonAppelOffresLimite-eng",
  "limitedTenderingReason-raisonAppelOffresLimite-fra",
  "tradeAgreements-accordsCommerciaux-eng",
  "tradeAgreements-accordsCommerciaux-fra",
  "regionsOfDelivery-regionsLivraison-eng",
  "regionsOfDelivery-regionsLivraison-fra",
  "supplierLegalName-nomLegalFournisseur-eng",
  "supplierAddressLine-ligneAdresseFournisseur-eng",
  "supplierAddressCity-fournisseurAdresseVille-eng",
  "supplierAddressProvince-fournisseurAdresseProvince-eng",
  "supplierAddressPostalCode-fournisseurAdresseCodePostal",
  "supplierAddressCountry-fournisseurAdressePays-eng",
  "supplierLegalName-nomLegalFournisseur-fra",
  "supplierAddressLine-ligneAdresseFournisseur-fra",
  "supplierAddressCity-fournisseurAdresseVille-fra",
  "supplierAddressProvince-fournisseurAdresseProvince-fra",
  "supplierAddressCountry-fournisseurAdressePays-fra",
  "contractingEntityName-nomEntitContractante-eng",
  "contractingEntityAddressLine-ligneAdresseEntiteContractante-eng",
  "contractingEntityAddressCity-entiteContractanteAdresseVille-eng",
  "contractingEntityAddressProvince-entiteContractanteAdresseProvince-eng",
  "contractingEntityAddressPostalCode-entiteContractanteAdresseCodePostal",
  "contractingEntityAddressCountry-entiteContractanteAdressePays-eng",
  "contractingEntityName-nomEntitContractante-fra",
  "contractingEntityAddressLine-ligneAdresseEntiteContractante-fra",
  "contractingEntityAddressCity-entiteContractanteAdresseVille-fra",
  "contractingEntityAddressProvince-entiteContractanteAdresseProvince-fra",
  "contractingEntityAddressCountry-entiteContractanteAdressePays-fra",
  "endUserEntitiesName-nomEntitesUtilisateurFinal-eng",
  "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-eng",
  "endUserEntitiesName-nomEntitesUtilisateurFinal-fra",
  "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-fra",
  "contactInfoName-informationsContactNom",
  "contactInfoEmail-informationsContactCourriel",
  "contactInfoPhone-contactInfoTelephone",
  "contactInfoFax",
  "contactInfoAddressLine-contactInfoAdresseLigne-eng",
  "contactInfoCity-contacterInfoVille-eng",
  "contactInfoProvince-contacterInfoProvince-eng",
  "contactInfoPostalcode",
  "contactInfoCountry-contactInfoPays-eng",
  "contactInfoAddressLine-contactInfoAdresseLigne-fra",
  "contactInfoCity-contacterInfoVille-fra",
  "contactInfoProvince-contacterInfoProvince-fra",
  "contactInfoCountry-contactInfoPays-fra",
  "awardDescription-descriptionAttribution-eng",
  "awardDescription-descriptionAttribution-fra"
 ],
 "contracts": [
  "title-titre-eng",
  "title-titre-fra",
  "referenceNumber-numeroReference",
  "amendmentNumber-numeroModification",
  "procurementNumber-numeroApprovisionnement",
  "solicitationNumber-numeroSollicitation",
  "contractNumber-numeroContrat",
  "numberOfRecords-nombreEnregistrements",
  "publicationDate-datePublication",
  "contractAwardDate-dateAttributionContrat",
  "amendmentDate-dateModification",
  "contractStartDate-contratDateDebut",
  "contractEndDate-dateFinContrat",
  "contractAmount-montantContrat",
  "totalContractValue-valeurTotaleContrat",
  "contractCurrency-contratMonnaie",
  "contractStatus-statutContrat-eng",
  "contractStatus-statutContrat-fra",
  "instrumentType-typeInstrument-eng",
  "instrumentType-typeInstrument-fra",
  "amendmentType-typeModification-eng",
  "amendmentType-typeModification-fra",
  "gsin-nibs",
  "gsinDescription-nibsDescription-eng",
  "gsinDescription-nibsDescription-fra",
  "unspsc",
  "unspscDescription-eng",
  "unspscDescription-fra",
  "procurementCategory-categorieApprovisionnement",
  "noticeType-avisType-eng",
  "noticeType-avisType-fra",
  "procurementMethod-methodeApprovisionnement-eng",
  "procurementMethod-methodeApprovisionnement-fra",
  "selectionCriteria-criteresSelection-eng",
  "selectionCriteria-criteresSelection-fra",
  "limitedTenderingReason-raisonAppelOffresLimite-eng",
  "limitedTenderingReason-raisonAppelOffresLimite-fra",
  "tradeAgreements-accordsCommerciaux-eng",
  "tradeAgreements-accordsCommerciaux-fra",
  "regionsOfDelivery-regionsLivraison-eng",
  "regionsOfDelivery-regionsLivraison-fra",
  "supplierLegalName-nomLegalFournisseur-eng",
  "supplierLegalName-nomLegalFournisseur-fra",
  "supplierStandardizedName-nomNormaliseFournisseur-eng",
  "supplierStandardizedName-nomNormaliseFournisseur-fra",
  "supplierOperatingName-nomCommercialFournisseur-eng",
  "supplierOperatingName-nomCommercialFournisseur-fra",
  "supplierEmployeeCount-fournisseurNombreEmployes-eng",
  "supplierEmployeeCount-fournisseurNombreEmployes-fra",
  "supplierAddressLine-ligneAdresseFournisseur-eng",
  "supplierAddressLine-ligneAdresseFournisseur-fra",
  "supplierAddressCity-fournisseurAdresseVille-eng",
  "supplierAddressCity-fournisseurAdresseVille-fra",
  "supplierAddressProvince-fournisseurAdresseProvince-eng",
  "supplierAddressProvince-fournisseurAdresseProvince-fra",
  "supplierAddressPostalCode-fournisseurAdresseCodePostal",
  "supplierAddressCountry-fournisseurAdressePays-eng",
  "supplierAddressCountry-fournisseurAdressePays-fra",
  "contractingEntityName-nomEntitContractante-eng",
  "contractingEntityName-nomEntitContractante-fra",
  "contractingEntityAddressLine-ligneAdresseEntiteContractante-eng",
  "contractingEntityAddressLine-ligneAdresseEntiteContractante-fra",
  "contractingEntityAddressCity-entiteContractanteAdresseVille-eng",
  "contractingEntityAddressCity-entiteContractanteAdresseVille-fra",
  "contractingEntityAddressProvince-entiteContractanteAdresseProvince-eng",
  "contractingEntityAddressProvince-entiteContractanteAdresseProvince-fra",
  "contractingEntityAddressPostalCode-entiteContractanteAdresseCodePostal",
  "contractingEntityAddressCountry-entiteContractanteAdressePays-eng",
  "contractingEntityAddressCountry-entiteContractanteAdressePays-fra",
  "endUserEntitiesName-nomEntitesUtilisateurFinal-eng",
  "endUserEntitiesName-nomEntitesUtilisateurFinal-fra",
  "endUserEntitiesOfficeName-bureauNomEntitesUtilisateurFinal-eng",
  "endUserEntitiesOfficeName-bureauNomEntitesUtilisateurFinal-fra",
  "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-eng",
  "endUserEntitiesAddress-adresseEntitesUtilisateurFinal-fra",
  "contactInfoName-informationsContactNom",
  "contactInfoEmail-informationsContactCourriel",
  "contactInfoPhone-contactInfoTelephone",
  "contactInfoFax",
  "contactInfoAddressLine-contactInfoAdresseLigne-eng",
  "contactInfoAddressLine-contactInfoAdresseLigne-fra",
  "contactInfoCity-contacterInfoVille-eng",
  "contactInfoCity-contacterInfoVille-fra",
  "contactInfoProvince-contacterInfoProvince-eng",
  "contactInfoProvince-contacterInfoProvince-fra",
  "contactInfoPostalcode",
  "contactInfoCountry-contactInfoPays-eng",
  "contactInfoCountry-contactInfoPays-fra",
  "percentageOfGoodsByCountry-pourcentageDeBiensParPays",
  "tenderDescription-descriptionAppelOffres-eng",
  "tenderDescription-descriptionAppelOffres-fra"
 ]
}


def write(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


PW = "Public Works and Government Services Canada"
CSC = "Correctional Service of Canada"
DND = "Department of National Defence"


def tender(i, year, gsin="*N7110", desc="*Office Furniture", end_user=CSC, cat="*GD", status="Expired"):
    sol = f"21120-{i:06d}"
    return {
        "title-titre-eng": f"Office furniture {year} ({sol})", "title-titre-fra": f"Mobilier de bureau {year}",
        "referenceNumber-numeroReference": f"PW-{year % 100:02d}-{i:08d}", "amendmentNumber-numeroModification": "000",
        "solicitationNumber-numeroSollicitation": sol, "publicationDate-datePublication": f"{year}-05-03",
        "tenderClosingDate-appelOffresDateCloture": f"{year}-06-01T14:00:00", "tenderStatus-appelOffresStatut-eng": status,
        "gsin-nibs": gsin, "gsinDescription-nibsDescription-eng": desc, "procurementCategory-categorieApprovisionnement": cat,
        "noticeType-avisType-eng": "Request for Proposal", "procurementMethod-methodeApprovisionnement-eng": "Competitive - Open bidding",
        "tradeAgreements-accordsCommerciaux-eng": "*Canadian Free Trade Agreement (CFTA)\n*World Trade Organization Agreement on Government Procurement (WTO GPA)",
        "regionsOfDelivery-regionsLivraison-eng": "*Ontario (except NCR)\n*Quebec (except NCR)",
        "contractingEntityName-nomEntitContractante-eng": PW, "endUserEntitiesName-nomEntitesUtilisateurFinal-eng": end_user,
        "contactInfoName-informationsContactNom": "Buyer Name", "contactInfoEmail-informationsContactCourriel": "buyer@example.gc.ca",
        "tenderDescription-descriptionAppelOffres-eng": "Supply and delivery of office furniture, line 1\nline 2, with commas",
    }


def contract(i, year, amend="000", end=None, total=None, amount=None, supplier=("Acme Furniture Ltd.", "ACME FURNITURE"),
             gsin="*N7110", desc="*Office Furniture", end_user=CSC, cat="*GD", award=None, instrument="", amend_type=""):
    sol = f"21120-{i:06d}"
    ref = f"{sol}/001/PR"
    return {
        "title-titre-eng": f"{supplier[1]} ({ref}~{amend})", "referenceNumber-numeroReference": ref,
        "amendmentNumber-numeroModification": amend, "procurementNumber-numeroApprovisionnement": sol,
        "contractNumber-numeroContrat": ref, "numberOfRecords-nombreEnregistrements": "2",
        "contractAwardDate-dateAttributionContrat": (award or f"{year}-07-02") if amend == "000" else "",
        "amendmentDate-dateModification": "" if amend == "000" else f"{year + 1}-01-15",
        "contractEndDate-dateFinContrat": end or f"{year + 1}-03-31",
        "contractAmount-montantContrat": amount or "100000.00", "totalContractValue-valeurTotaleContrat": total or "100000.00",
        "contractCurrency-contratMonnaie": "CAD", "instrumentType-typeInstrument-eng": instrument,
        "amendmentType-typeModification-eng": amend_type,
        "gsin-nibs": gsin, "gsinDescription-nibsDescription-eng": desc, "procurementCategory-categorieApprovisionnement": cat,
        "procurementMethod-methodeApprovisionnement-eng": "Competitive - Open bidding",
        "supplierLegalName-nomLegalFournisseur-eng": supplier[0], "supplierStandardizedName-nomNormaliseFournisseur-eng": supplier[1],
        "supplierOperatingName-nomCommercialFournisseur-eng": supplier[0],
        "contractingEntityName-nomEntitContractante-eng": PW, "endUserEntitiesName-nomEntitesUtilisateurFinal-eng": end_user,
        "tradeAgreements-accordsCommerciaux-eng": "*Canadian Free Trade Agreement (CFTA)",
    }


def award(ref, contract_no, pub, end, supplier, status="Active", gsin="*N7110", desc="*Office Furniture", cat="*GD",
          buyer=PW, end_user=CSC, amount="100000.00"):
    return {
        "title-titre-eng": f"Award {ref}", "referenceNumber-numeroReference": ref, "amendmentNumber-numeroModification": "000",
        "solicitationNumber-numeroSollicitation": contract_no.split("/")[0] if contract_no else ref,
        "contractNumber-numeroContrat": contract_no, "publicationDate-datePublication": pub,
        "contractAwardDate-dateAttributionContrat": pub, "contractEndDate-dateFinContrat": end,
        "contractAmount-montantContrat": amount, "totalContractValue-valeurTotaleContrat": "0.00",
        "contractCurrency-contratMonnaie": "CAD", "awardStatus-attributionStatut-eng": status,
        "gsin-nibs": gsin, "gsinDescription-nibsDescription-eng": desc, "procurementCategory-categorieApprovisionnement": cat,
        "procurementMethod-methodeApprovisionnement-eng": "Competitive - Open bidding",
        "tradeAgreements-accordsCommerciaux-eng": "*Canadian Free Trade Agreement (CFTA)\n*Canada-Chile Free Trade Agreement (CCFTA)",
        "supplierLegalName-nomLegalFournisseur-eng": supplier, "contractingEntityName-nomEntitContractante-eng": buyer,
        "endUserEntitiesName-nomEntitesUtilisateurFinal-eng": end_user, "awardDescription-descriptionAttribution-eng": "Award",
    }


def main() -> None:
    d = HERE / "canadabuys"
    # tenders: legacy 2019-2021, complete 2022-2025 (+ a DND services tender)
    legacy_t = [tender(i, 2018 + i) for i in range(1, 4)]                       # 2019, 2020, 2021
    complete_t = [tender(i, 2018 + i) for i in range(4, 7)]                     # 2022, 2023, 2024
    complete_t.append(tender(7, 2024, gsin="*R019BF", desc="*Engineering Services", end_user=DND, cat="*SRV"))
    write(d / "2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv", HEADERS["tenders"], legacy_t)
    write(d / "tenderNoticeComplete-avisAppelOffresComplet.csv", HEADERS["tenders"], complete_t)
    # contracts: one per tender, awarded 2 months after; contract 6 ends 2027-03-31 after an extension
    legacy_c = [contract(i, 2018 + i) for i in range(1, 4)]
    complete_c = [contract(i, 2018 + i) for i in range(4, 6)]
    complete_c.append(contract(6, 2024, end="2026-12-31", total="250000.00", amount="250000.00", instrument="Standing Offer"))
    complete_c.append(contract(6, 2024, amend="001", end="2027-03-31", total="300000.00", amount="50000.00",
                               instrument="Standing Offer", amend_type="Amendment"))
    complete_c.append(contract(7, 2024, end="2027-05-31", gsin="*R019BF", desc="*Engineering Services", end_user=DND,
                               cat="*SRV", supplier=("Beta Engineering Inc.", "BETA ENGINEERING")))
    complete_c.append(contract(8, 2025, end="2027-02-28", award="2025-06-01", supplier=("Gamma Chairs Inc.", "GAMMA CHAIRS")))
    complete_c.append(contract(8, 2025, amend="001", end="2027-02-28", amend_type="Termination",
                               supplier=("Gamma Chairs Inc.", "GAMMA CHAIRS")))
    write(d / "2009-2023-contractHistoryHistorical-contratsOctroyesHistorique.csv", HEADERS["contracts"], legacy_c)
    write(d / "contractHistoryComplete-contratsOctroyesComplet.csv", HEADERS["contracts"], complete_c)
    # awards: legacy one, complete twin of contract 6 (to be deduplicated), and a DND goods award with legal name only
    legacy_a = [award("W8484-127434:001:EEM", "W8484-127434/001/EEM", "2015-03-02", "2016-03-31", "Delta Supply Inc.",
                      buyer=PW, end_user=DND)]
    complete_a = [award("MX-0000000001", "21120-000006/001/PR", "2024-07-02", "2027-03-31", "Acme Furniture Ltd."),
                  award("MX-0000000002", "", "2025-02-10", "2027-01-15", "Acme Furniture Limited", end_user=DND,
                        buyer="Department of National Defence (DND)")]
    write(d / "2012-2022-awardNoticeHistorical-avisAttributionHistorique.csv", HEADERS["awards"], legacy_a)
    write(d / "awardNoticeComplete-avisAttributionComplet.csv", HEADERS["awards"], complete_a)
    # daily files (fiscal year 2026-2027)
    reordered = dict(complete_t[2])
    reordered["regionsOfDelivery-regionsLivraison-eng"] = "*Quebec (except NCR)\n*Ontario (except NCR)"
    new_tender = tender(9, 2026)
    new_tender["publicationDate-datePublication"] = "2026-11-22"
    write(d / "2026-2027-TenderNotice-AvisAppelOffres.csv", HEADERS["tenders"], [reordered])
    write(d / "newTenderNotice-nouvelAvisAppelOffres.csv", HEADERS["tenders"], [new_tender])
    write(d / "openTenderNotice-ouvertAvisAppelOffres.csv", HEADERS["tenders"], [])
    changed = dict(complete_a[1])
    changed["awardStatus-attributionStatut-eng"] = "Expired"
    write(d / "2026-2027-awardNotice-avisAttribution.csv", HEADERS["awards"], [changed])
    write(d / "2026-2027-contractHistory-contratsOctroyes.csv", HEADERS["contracts"], complete_c[-2:])

    t = HERE / "toronto"
    sol_header = ["_id", "Document Number", "RFx (Solicitation) Type", "NOIP (Notice of Intended Procurement) Type",
                  "Issue Date", "Submission Deadline", "High Level Category", "Solicitation Document Description",
                  "Division", "Buyer Name", "Buyer Email", "Buyer Phone Number", "Wards"]
    write(t / "all-solicitations.csv", sol_header, [
        {"_id": "1", "Document Number": "3202107273", "RFx (Solicitation) Type": "RFQ",
         "NOIP (Notice of Intended Procurement) Type": "Notice of Intended Procurement", "Issue Date": "2026-10-14",
         "Submission Deadline": "2026-11-03", "High Level Category": "Goods and Services",
         "Solicitation Document Description": "Supply of road salt", "Division": "Transportation Services",
         "Buyer Name": "A Buyer", "Buyer Email": "supplychain@toronto.ca"}])
    awd_header = ["_id", "Document Number", "RFx (Solicitation) Type", "High Level Category", "Award",
                  "Award Authority Obtained Date", "Division", "Buyer Name", "Buyer Email", "Buyer Phone Number",
                  "Solicitation Document Description", "Supplier Address", "Wards"]
    awards_json = ('[{"Award_Amount": "26,773.58", "AwardedDate": null, "Cancellation_Date": null, "Date_Awarded": "2012-10-04", '
                   '"Initial_Contract_Val": null, "Successful_Bidder": "Computer Media Group", "city": "MISSISSAUGA", '
                   '"country": "CANADA", "postalCode": "L5T 2N5", "province": "ON", "street": "1 Main St"}, '
                   '{"Award_Amount": "771931.57", "AwardedDate": null, "Cancellation_Date": null, "Date_Awarded": "2012-10-04", '
                   '"Initial_Contract_Val": null, "Successful_Bidder": "ASCA Office Solutions", "city": "TORONTO", '
                   '"country": "CANADA", "postalCode": "M9L 1Z6", "province": "ON", "street": "2 Main St"}]')
    rows = [{"_id": str(i), "Document Number": "3303123110", "RFx (Solicitation) Type": "RFQ",
             "High Level Category": "Goods and Services", "Award": awards_json, "Award Authority Obtained Date": "2012-10-04",
             "Division": "Purchasing & Materials Management", "Buyer Name": "A Buyer", "Buyer Email": "supplychain@toronto.ca",
             "Solicitation Document Description": "Office supplies"} for i in (1, 2)]   # the list repeats on each row
    write(t / "awarded-contracts.csv", awd_header, rows)


if __name__ == "__main__":
    main()
