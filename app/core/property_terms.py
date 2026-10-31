"""Dutch/English property-management vocabulary (ADR 0008): the same idea in the words a lease, a tenant and the owner
use. Pure data and two helpers. Search expands a question with the other language's words; the offline embedder
maps words of one idea to one feature, so tests can show cross-language retrieval without a model.
"""

import re
import unicodedata

from rapidfuzz import fuzz, process

GROUPS: dict[str, tuple[str, ...]] = {
    "deposit": ("deposit", "security deposit", "waarborgsom", "borgsom", "borg"),
    "notice": ("notice", "notice period", "opzegtermijn", "opzegging", "opzeggen", "opzeg"),
    "rent": ("rent", "monthly rent", "huur", "huurprijs", "kale huur", "maandhuur", "huurbedrag"),
    "lease": ("lease", "tenancy agreement", "rental agreement", "huurovereenkomst", "huurcontract", "contract"),
    "tenant": ("tenant", "huurder", "huurders"),
    "landlord": ("landlord", "owner", "verhuurder", "eigenaar"),
    "invoice": ("invoice", "bill", "factuur", "nota", "rekening"),
    "quote": ("quote", "quotation", "estimate", "offerte", "prijsopgave"),
    "insurance": ("insurance", "policy", "verzekering", "polis", "opstalverzekering"),
    "certificate": ("certificate", "inspection", "keuring", "certificaat", "energielabel", "energy label"),
    "maintenance": ("maintenance", "repair", "onderhoud", "reparatie", "herstel", "herstellen"),
    "leak": ("leak", "leakage", "lek", "lekkage", "lekt"),
    "service": ("service costs", "service charges", "servicekosten", "stookkosten", "bijkomende kosten"),
    "indexation": ("indexation", "rent increase", "indexering", "huurverhoging", "huurindexatie"),
    "term": ("term", "duration", "end date", "looptijd", "duur", "einddatum", "ingangsdatum", "expiry"),
    "pets": ("pets", "pet", "animals", "huisdieren", "huisdier", "dieren"),
    "sublet": ("sublet", "subletting", "onderhuur", "onderverhuur", "onderverhuren"),
    "smoking": ("smoking", "smoke", "roken", "rookverbod"),
    "keys": ("keys", "key", "sleutel", "sleutels"),
    "termination": ("termination", "terminate", "beeindiging", "beeindigen", "ontbinding"),
    "handover": ("handover", "check-in", "oplevering", "opname", "inspectie", "overdracht"),
    "damage": ("damage", "defect", "schade", "gebrek", "gebreken"),
    "payment": ("payment", "pay", "betaling", "betalen", "betaald"),
    "arrears": ("arrears", "overdue", "late payment", "achterstand", "te laat", "betalingsachterstand"),
    "heating": ("heating", "boiler", "verwarming", "cv", "ketel", "cv-ketel"),
    "renovation": ("renovation", "refurbishment", "verbouwing", "renovatie"),
    "utilities": ("utilities", "gas", "water", "electricity", "nutsvoorzieningen", "stroom", "elektra"),
    "warranty": ("warranty", "guarantee", "garantie"),
    "notice_of_default": ("notice of default", "ingebrekestelling"),
}
_FUNCTION_WORDS = (
    "the a an and or of to in on at for is are was were be been it its this that with by from as what does do did how "
    "say says said tell about de het een en of van in op te voor met door uit als wat hoe is zijn was waren wordt "
    "worden dat dit die er ook bij naar om aan dan maar niet geen kan kunnen moet moeten heeft hebben"
)
_STOPWORDS = frozenset(_FUNCTION_WORDS.split())
_WORD = re.compile(r"[^\W_]{2,}(?:-[^\W_]+)*")


def fold(text: str) -> str:
    """Lower-case, accents removed (`beëindiging` = `beeindiging`)."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _index() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, terms in GROUPS.items():
        for term in terms:
            for word in _WORD.findall(fold(term)):
                out.setdefault(word, key)
    return out


_WORD_TO_GROUP = _index()
_PHRASES = [
    (re.compile(rf"(?<!\w){re.escape(fold(t))}(?!\w)"), key) for key, ts in GROUPS.items() for t in ts if " " in t
]


def groups_in(text: str) -> list[str]:
    """The idea groups a text touches (phrases first, then single words), in order of first appearance."""
    low = fold(text)
    found: list[str] = []
    for pattern, key in _PHRASES:
        if pattern.search(low) and key not in found:
            found.append(key)
    for word in _WORD.findall(low):
        group = _WORD_TO_GROUP.get(word)
        if group and group not in found:
            found.append(group)
    return found


def expand(text: str) -> list[str]:
    """Other-language and synonym words for the ideas in `text` (single words only: they feed keyword search)."""
    seen = set(_WORD.findall(fold(text)))
    out: list[str] = []
    for key in groups_in(text):
        for term in GROUPS[key]:
            word = fold(term)
            if " " not in word and word not in seen:
                seen.add(word)
                out.append(word)
    return out


def canonical_tokens(text: str) -> list[str]:
    """Tokens of `text` without function words, every glossary word replaced by its idea (the fake embedder's
    vocabulary)."""
    return [_WORD_TO_GROUP.get(w, w) for w in _WORD.findall(fold(text)) if w not in _STOPWORDS]


ITEM_TERMS: dict[str, tuple[str, ...]] = {
    "boiler_service": (
        "boiler service",
        "boiler maintenance",
        "boiler servicing",
        "cv ketel onderhoud",
        "cv onderhoud",
        "cv-ketel onderhoud",
        "ketelonderhoud",
        "ketel onderhoud",
        "onderhoud cv ketel",
        "onderhoud ketel",
    ),
    "leak_repair": (
        "leak repair",
        "fix leak",
        "leaking",
        "lekkage reparatie",
        "lekkage",
        "lekkage herstel",
        "lek repareren",
        "reparatie lekkage",
    ),
    "painting": ("painting", "paint work", "painter", "schilderwerk", "schilderen", "schilder", "verven"),
    "plumbing": ("plumbing", "plumber", "loodgieter", "loodgieterswerk", "sanitair", "verstopping", "blocked drain"),
    "electrical_repair": (
        "electrical repair",
        "electrician",
        "electrical work",
        "elektra reparatie",
        "elektricien",
        "elektrawerk",
    ),
    "cleaning": ("cleaning", "deep clean", "schoonmaak", "schoonmaken", "eindschoonmaak", "reiniging"),
    "locksmith": ("locksmith", "lock replacement", "change locks", "slotenmaker", "slot vervangen", "sleutelservice"),
    "roof_repair": ("roof repair", "roofing", "dakreparatie", "dakwerk", "dakbedekking", "dakgoot"),
    "window_repair": ("window repair", "glass repair", "glaszetter", "raamreparatie", "glas vervangen", "ramen"),
    "gardening": ("gardening", "garden maintenance", "tuinonderhoud", "tuinwerk", "hovenier", "tuinman"),
    "pest_control": ("pest control", "exterminator", "ongediertebestrijding", "ongedierte", "plaagdierbestrijding"),
    "flooring": ("flooring", "floor repair", "laminate", "vloer", "vloeren", "vloerbedekking", "parket"),
    "call_out_fee": ("call-out fee", "call out fee", "callout", "travel costs", "voorrijkosten", "voorrijdkosten"),
    "labour": ("labour", "labor", "hourly rate", "arbeid", "arbeidsloon", "uurloon", "manuren"),
    "materials": ("materials", "material costs", "materiaal", "materialen", "materiaalkosten"),
}
_FUZZY_CUTOFF = 90
_SLUG_WORDS = 4
_ALNUM = re.compile(r"[a-z0-9]+")


def _term_table() -> list[tuple[re.Pattern[str], str]]:
    """Every term, longest first, so the most specific phrase wins (`cv ketel onderhoud` before `onderhoud`)."""
    rows = [(fold(t), key) for key, terms in ITEM_TERMS.items() for t in terms]
    rows.sort(key=lambda r: (-len(r[0]), r[0]))
    return [(re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"), key) for term, key in rows]


_ITEM_PATTERNS = _term_table()
_ITEM_FOLDED = {fold(t): key for key, terms in ITEM_TERMS.items() for t in terms}
_ITEM_TERMS_FOLDED = list(_ITEM_FOLDED)


def _fuzzy_key(low: str) -> str | None:
    """Typo tolerance: the whole text, then each word, against the term table (cutoff 90)."""
    for candidate in [low, *_ALNUM.findall(low)]:
        if len(candidate) < 5:
            continue
        hit = process.extractOne(candidate, _ITEM_TERMS_FOLDED, scorer=fuzz.ratio, score_cutoff=_FUZZY_CUTOFF)
        if hit is not None:
            return _ITEM_FOLDED[hit[0]]
    return None


def normalise_item_key(description: str) -> str:
    """Stable key for a job line, so a Dutch and an English line for the same work meet (`Cv ketel onderhoud` and
    `boiler service` are `boiler_service`). Known term, then a near-miss spelling, else a slug of up to 4 words."""
    low = fold(description).strip()
    for pattern, key in _ITEM_PATTERNS:
        if pattern.search(low):
            return key
    fuzzy = _fuzzy_key(low)
    if fuzzy is not None:
        return fuzzy
    words = [w for w in _ALNUM.findall(low) if w not in _STOPWORDS]
    return "_".join(words[:_SLUG_WORDS]) or "other"
