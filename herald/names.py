"""Deterministic name matching for suppliers and buyers. No model, no fuzzy scores: the same input always gives
the same key, and every rule is written out here so a desk can see why two names were joined.

Suppliers: the files' standardized supplier name (contract history's `supplierStandardizedName`) comes first.
Where a row has none, the legal name is used. Both go through `supplier_key`, which upper-cases, strips accents
and punctuation, spells out `&`, drops a leading THE and trailing legal-form words (INC, LTD, LIMITED, CORP, ...),
and collapses spaces. The views then join a legal-name key to a standardized-name key when contract history pairs
them one-to-one (herald/views.py, `supplier_map`).

Buyers: `buyer_key` strips a trailing "(ABC)" acronym, a leading "Department of"/"Ministère de", a trailing
"Canada"/"Agency", then applies ref/buyer_aliases.csv (normalized name -> canonical key) for the names the rules
can't join (PWGSC and PSPC, for example).
"""

from __future__ import annotations

import csv
import functools
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_LEGAL_FORMS = (
    "INCORPORATED", "INCORPOREE", "INC", "LIMITED", "LIMITEE", "LTD", "LTEE", "LTE", "LLC", "LLP", "LP", "ULC",
    "CORPORATION", "CORP", "COMPANY", "CO", "PLC", "GMBH", "AG", "SA", "SAS", "SARL", "SRL", "SPA", "BV", "NV",
    "AB", "AS", "OY", "PTY", "KG", "SENC", "SENCRL", "S E N C", "S E N C R L", "CIE", "ET CIE",
    "S A", "S A S", "S R L", "S P A", "B V", "N V", "L P", "L L C", "U L C",
)
_LEGAL_RE = re.compile(r"(?:\s+(?:" + "|".join(re.escape(f) for f in sorted(_LEGAL_FORMS, key=len, reverse=True))
                       + r"))+$")
_PUNCT_RE = re.compile(r"[^A-Z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")
_PAREN_TAIL_RE = re.compile(r"\s*\([^)]*\)\s*$")
_INITIALS_RE = re.compile(r"\b(?:[A-Z0-9] )+[A-Z0-9]\b")
_DBA_RE = re.compile(r"\s+(?:DBA|O/A|OPERATING AS|DOING BUSINESS AS|FAISANT AFFAIRE SOUS)\s+.*$")


def fold(s: str | None) -> str:
    """Upper case, accents removed, & spelled out, punctuation to spaces, spaces collapsed."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = s.replace("&", " AND ").replace("'", "").replace("’", "")
    s = _PUNCT_RE.sub(" ", s)
    return _SPACE_RE.sub(" ", s).strip()


def supplier_key(name: str | None) -> str | None:
    """The matching key for a supplier name; None for an empty name."""
    if not name or not name.strip():
        return None
    s = name.upper()
    halves = re.split(r"\s*/\s*", s, maxsplit=1)   # bilingual "IBM CANADA LTD/IBM CANADA LIMITEE" -> the first
    if len(halves) == 2 and len(halves[0].strip()) >= 3 and len(halves[1].strip()) >= 3:
        s = halves[0]
    s = _DBA_RE.sub("", s)          # "X INC DBA Y" -> "X INC": the legal person is what wins the contract
    s = fold(s)
    s = _INITIALS_RE.sub(lambda m: m.group(0).replace(" ", ""), s)   # "C G I" (from C.G.I.) -> "CGI"
    if s.startswith("THE "):
        s = s[4:]
    prev = None
    while prev != s:                # "ACME CANADA LTD INC" -> "ACME CANADA"
        prev = s
        s = _LEGAL_RE.sub("", s).strip()
    return s or fold(name) or None


@functools.lru_cache(maxsize=1)
def _buyer_aliases() -> dict[str, str]:
    p = REPO_ROOT / "ref" / "buyer_aliases.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {fold(r["name"]): r["key"] for r in csv.DictReader(f) if r.get("name") and r.get("key")}


def buyer_key(name: str | None) -> str | None:
    """The matching key for a buying organization; None for an empty name."""
    if not name or not name.strip():
        return None
    first = name.split("\n")[0].split(";")[0].strip()   # multi-valued end users: the first is the key
    first = re.split(r"\s+[-/]\s+", first)[0]           # "X - Ontario Region", "X / X en français" -> "X"
    s = _PAREN_TAIL_RE.sub("", first)
    s = fold(s)
    aliases = _buyer_aliases()
    if s in aliases:
        return aliases[s]
    if s.startswith("THE "):
        s = s[4:]
    if s.endswith(" THE"):                                   # "Senate, The"
        s = s[:-4]
    for prefix in ("DEPARTMENT OF THE ", "DEPARTMENT OF ", "MINISTERE DE LA ", "MINISTERE DES ", "MINISTERE DU ",
                   "MINISTERE DE L ", "MINISTERE DE "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    prev = None
    while prev != s:                                         # "PARKS CANADA AGENCY" -> "PARKS"
        prev = s
        for suffix in (" OF CANADA", " CANADA", " AGENCY"):
            if s.endswith(suffix) and len(s) > len(suffix) + 3:
                s = s[: -len(suffix)]
    return aliases.get(s, s) or None
