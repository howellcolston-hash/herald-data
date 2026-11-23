import unittest

from herald.names import buyer_key, supplier_key


class SupplierKeyTest(unittest.TestCase):
    def test_legal_forms_and_punctuation(self):
        self.assertEqual(supplier_key("Acme Furniture Ltd."), "ACME FURNITURE")
        self.assertEqual(supplier_key("ACME FURNITURE LIMITED"), "ACME FURNITURE")
        self.assertEqual(supplier_key("Acme Corp., Inc."), "ACME")
        self.assertEqual(supplier_key("Société Générale S.A."), "SOCIETE GENERALE")

    def test_bilingual_dba_initials_and_the(self):
        self.assertEqual(supplier_key("IBM CANADA LTD/IBM CANADA LIMITEE"), "IBM CANADA")
        self.assertEqual(supplier_key("Incite Experiential Design INC DBA RMUS Canada"), "INCITE EXPERIENTIAL DESIGN")
        self.assertEqual(supplier_key("C.G.I. Information Systems Inc"), supplier_key("CGI Information Systems Inc."))
        self.assertEqual(supplier_key("The Delta Partners"), "DELTA PARTNERS")

    def test_numbered_companies_and_empty(self):
        self.assertEqual(supplier_key("2060945 ONTARIO INC."), "2060945 ONTARIO")
        self.assertIsNone(supplier_key(""))
        self.assertIsNone(supplier_key(None))


class BuyerKeyTest(unittest.TestCase):
    def test_pspc_variants_join(self):
        keys = {buyer_key(n) for n in ["Public Works and Government Services Canada",
                                       "Department of Public Works and Government Services (PSPC)",
                                       "Public Services and Procurement Canada (PSPC)", "PWGSC"]}
        self.assertEqual(keys, {"PUBLIC WORKS AND GOVERNMENT SERVICES"})

    def test_rules(self):
        self.assertEqual(buyer_key("Department of National Defence (DND)"), buyer_key("National Defence"))
        self.assertEqual(buyer_key("Fisheries and Oceans Canada (DFO)"), buyer_key("Department of Fisheries and Oceans"))
        self.assertEqual(buyer_key("Parks Canada Agency (PC)"), buyer_key("Parks Canada"))
        self.assertEqual(buyer_key("Senate, The"), "SENATE")
        self.assertEqual(buyer_key("Defence Construction Canada - Ontario Region"), buyer_key("Defence Construction Canada"))
        self.assertEqual(buyer_key("Global Affairs Canada"), buyer_key("Department of Foreign Affairs, Trade and Development"))

    def test_multi_valued_takes_first(self):
        self.assertEqual(buyer_key("Correctional Service of Canada; Department of National Defence"), "CORRECTIONAL SERVICE")


if __name__ == "__main__":
    unittest.main()
