"""Deterministic stand-in for the dd_reader model (offline tests, eval, simulation).

Reads labelled lines (`Vraagprijs: € 450.000,-`, `Woonoppervlakte: 95 m2`) into claims whose quote is the line
itself, so quote verification always passes on honest text. Lines without a known label produce nothing, so text that
tries to steer the reader is ignored.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.contracts.diligence import FIELD_KIND, DDDocKind, DDField, ValueKind

_LINE = re.compile(r"^\s*([^:\n]{2,40}):\s*(.+?)\s*$")
_NUMBER = re.compile(r"\d[\d.,]*")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DMY = re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})")
_VALID = re.compile(r"(?:geldig tot|valid until|geldigheid)\D{0,12}(\d{4}-\d{2}-\d{2})", re.I)
_DATE_LINE = re.compile(r"^\s*(?:datum|date):\s*(\d{4}-\d{2}-\d{2})\s*$", re.I | re.M)
_THOUSANDS = re.compile(r"^\d{1,3}([.,]\d{3})+$")
_CENT = Decimal("0.01")
_ABSENT = ("niet aanwezig", "afwezig", "absent", "geen")

_KINDS: tuple[tuple[DDDocKind, tuple[str, ...]], ...] = (
    (DDDocKind.vve_minutes, ("notulen", "minutes")),
    (DDDocKind.vve_budget, ("begroting", "jaarrekening", "budget")),
    (DDDocKind.vve_maintenance_plan, ("meerjaren", "mjop", "maintenance plan")),
    (DDDocKind.vve_rules, ("splitsing", "reglement")),
    (DDDocKind.ground_lease, ("erfpacht", "ground lease")),
    (DDDocKind.energy_label, ("energielabel", "energy label")),
    (DDDocKind.building_survey, ("bouwkundig", "survey", "keuring")),
    (DDDocKind.asbestos_report, ("asbest",)),
    (DDDocKind.valuation, ("taxatie", "valuation")),
    (DDDocKind.permit, ("vergunning", "bestemmingsplan", "permit")),
    (DDDocKind.insurance, ("verzekering", "polis", "insurance")),
    (DDDocKind.lease_agreement, ("huurovereenkomst", "lease agreement")),
    (DDDocKind.rent_roll, ("huurspecificatie", "rent roll")),
    (DDDocKind.kadaster_extract, ("kadaster",)),
    (DDDocKind.deed_of_title, ("akte van levering", "eigendomsakte", "deed of title")),
    (DDDocKind.purchase_agreement, ("koopovereenkomst", "purchase agreement", "koopakte")),
    (DDDocKind.brochure, ("brochure",)),
)

_LABELS: tuple[tuple[DDField, tuple[str, ...]], ...] = (
    (DDField.ground_lease_end, ("einddatum erfpacht", "erfpacht tot", "ground lease end")),
    (DDField.tenancy_end, ("einddatum huur", "tenancy end", "lease end")),
    (DDField.ground_lease_fee, ("canon", "ground lease fee")),
    (DDField.vve_monthly_contribution, ("vve", "servicekosten", "service charge")),
    (DDField.monthly_rent, ("huurprijs", "monthly rent", "huur")),
    (DDField.price, ("vraagprijs", "koopsom", "purchase price", "asking price", "price")),
    (DDField.living_area_m2, ("woonoppervlakte", "gebruiksoppervlakte", "living area", "floor area")),
    (DDField.plot_area_m2, ("perceel", "plot", "kadastrale grootte")),
    (DDField.year_built, ("bouwjaar", "year built")),
    (DDField.energy_label, ("energielabel", "energy label")),
    (DDField.ownership_type, ("eigendomssituatie", "ownership", "eigendom")),
    (DDField.address, ("adres", "address")),
    (DDField.asbestos, ("asbest",)),
)

_FLAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("legal", ("geschil", "dispute", "rechtszaak", "litigation")),
    ("financial", ("achterstand", "arrears", "naheffing", "special levy", "extra bijdrage")),
    ("technical", ("lekkage", "leak", "funderingsprobleem", "foundation problem", "gebrek", "defect", "schimmel")),
)


def parse_amount(raw: str) -> Decimal | None:
    """The first number in `raw`, reading Dutch (`450.000,-`, `185,50`) and English (`1,250.50`) separators."""
    found = _NUMBER.search(raw)
    if found is None:
        return None
    token = found.group(0).rstrip(".,")
    if "," in token and "." in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        token = token.replace(thousands, "").replace(decimal_sep, ".")
    elif _THOUSANDS.match(token):
        token = re.sub(r"[.,]", "", token)
    else:
        token = token.replace(",", ".")
    try:
        return Decimal(token).quantize(_CENT, rounding=ROUND_HALF_UP)
    except ArithmeticError:
        return None


def _day(raw: str) -> date | None:
    iso, dmy = _ISO.search(raw), _DMY.search(raw)
    try:
        if iso:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if dmy:
            return date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))
    except ValueError:
        return None
    return None


def _field_of(label: str) -> DDField | None:
    low = label.casefold().strip()
    for field, words in _LABELS:
        if any(low == w or (len(w) > 4 and w in low) or (w in ("vve", "huur") and low.startswith(w)) for w in words):
            return field
    return None


def _claim(field: DDField, value: str, line: str) -> dict[str, object] | None:
    kind = FIELD_KIND[field]
    slots: dict[str, object] = {"field": field.value, "number": None, "text": None, "day": None, "quote": line[:200]}
    if kind is ValueKind.number:
        slots["number"] = parse_amount(value)
    elif kind is ValueKind.day:
        found = _day(value)
        slots["day"] = found.isoformat() if found else None
    elif field is DDField.asbestos:
        low = value.casefold()
        slots["text"] = (
            "absent" if any(w in low for w in _ABSENT) else "present" if "aanwezig" in low or "present" in low else None
        )
    else:
        text = value.split()[0].upper()[:6] if field is DDField.energy_label else value[:80]
        slots["text"] = text if text.strip() else None
    return slots if any(slots[k] is not None for k in ("number", "text", "day")) else None


def _kind_of(header: str, text: str) -> DDDocKind:
    for source in (header, text.casefold()):
        for kind, words in _KINDS:
            if any(w in source for w in words):
                return kind
    return DDDocKind.other


def _claims(lines: list[str]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for line in lines:
        m = _LINE.match(line)
        field = _field_of(m.group(1)) if m else None
        if m and field:
            claim = _claim(field, m.group(2), line.strip())
            if claim:
                out.append(claim)
    return out[:25]


def _flags(lines: list[str]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for line in lines:
        low = line.casefold()
        for category, words in _FLAGS:
            if not _LINE.match(line) and any(w in low for w in words):
                out.append({"category": category, "summary": line.strip()[:160], "quote": line.strip()[:240]})
                break
    return out[:6]


def fake_dd_reader(document: str, filename: str) -> dict[str, object]:
    text = "" if document == "none" else document
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = f"{filename} {lines[0] if lines else ''}".casefold()
    kind = _kind_of(header, text)
    claims, flags = _claims(lines), _flags(lines)
    dated, valid = _DATE_LINE.search(text), _VALID.search(text)
    sure = bool(lines) and (kind is not DDDocKind.other or bool(claims))
    return {
        "doc_kind": kind.value, "title": (lines[0].strip()[:80] if lines else filename[:80]) or "Document",
        "document_date": dated.group(1) if dated else None, "valid_until": valid.group(1) if valid else None,
        "claims": claims, "flags": flags, "confidence": 0.9 if sure else 0.4 if lines else 0.1,
    }  # fmt: skip
