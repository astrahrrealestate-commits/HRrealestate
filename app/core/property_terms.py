"""Dutch/English property-management vocabulary (ADR 0008): the same idea in the words a lease, a tenant and the owner
use. Pure data and two helpers. Search expands a question with the other language's words; the offline embedder
maps words of one idea to one feature, so tests can show cross-language retrieval without a model.
"""

import re
import unicodedata

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
