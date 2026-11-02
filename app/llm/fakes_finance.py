"""Deterministic stand-ins for the quote_reader and job_items models (offline tests, eval, simulation).

quote_reader reads the message, subject and attachment blocks line by line: an amount (`€ 120,00`, `EUR 99.50`,
`120 euro`) makes a line, `2 uur` / `3 hours` / `x 2` give quantity and unit, `per uur` / `x 2` make the amount a unit
price, `excl. BTW` / `incl. VAT` wording sets the VAT flag. A `Totaal` line is the total; one amount with no quantity
and no `Totaal` is a lump sum (total, no lines). Text with no amount, an invoice or a receipt is not a quote. Lines that
read like instructions ("ignore previous", "approved", "market price") are skipped, so injected text changes nothing.
job_items makes one item per sentence with a known maintenance term (`app.core.property_terms`), at most 10.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

from app.contracts.finance import MAX_JOB_ITEMS, MAX_QUANTITY, MAX_QUOTE_LINES
from app.core.property_terms import ITEM_TERMS, normalise_item_key

_AMOUNT = re.compile(
    r"(?:(?P<pre>€|EUR|USD|GBP|\$|£)\s*(?P<a>\d[\d.,]*)|(?P<b>\d[\d.,]*)\s*(?P<post>€|euro\b|EUR\b))", re.IGNORECASE
)
_CURRENCY = {"€": "EUR", "euro": "EUR", "eur": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP"}
_UNITS = {
    "uur": "hour", "uren": "hour", "hour": "hour", "hours": "hour", "hr": "hour", "hrs": "hour", "dag": "day",
    "dagen": "day", "day": "day", "days": "day", "stuk": "piece", "stuks": "piece", "st": "piece", "pcs": "piece",
    "piece": "piece", "pieces": "piece", "m2": "m2", "m²": "m2", "m": "m", "meter": "m",
}  # fmt: skip
_QTY = re.compile(rf"(\d+(?:[.,]\d+)?)\s*({'|'.join(sorted(_UNITS, key=len, reverse=True))})(?![\w²])", re.IGNORECASE)
_TIMES = re.compile(r"(?:\bx\s*(\d+)\b|\b(\d+)\s*x\b)", re.IGNORECASE)
_PER = re.compile(r"(?:\bper\b|\bà\b|\beach\b|/\s*(?:uur|hour|dag|day|stuk|m)\b|@)", re.IGNORECASE)
_PER_UNIT = re.compile(rf"(?:per|/)\s*({'|'.join(sorted(_UNITS, key=len, reverse=True))})(?![\w²])", re.IGNORECASE)
_EXCL = re.compile(r"\b(excl\.?|exclusief|ex\.?)\s*(btw|vat)\b|\b(btw|vat)\s*(excl\.?|exclusief)", re.IGNORECASE)
_INCL = re.compile(r"\b(incl\.?|inclusief|inc\.?)\s*(btw|vat)\b|\b(btw|vat)\s*(incl\.?|inclusief)", re.IGNORECASE)
_TOTAL = re.compile(r"\b(totaal|total|in totaal|te betalen|amount due|grand total)\b", re.IGNORECASE)
_SKIP = re.compile(
    r"^\W*(btw|vat)\b|\b(subtotaal|subtotal|korting|discount|credit|creditnota)\b"
    r"|ignore|negeer|disregard|approve|goedgekeurd|market price|marktprijs|instruction|instructie|system:|prompt",
    re.IGNORECASE,
)
_LUMP = re.compile(
    r"\b(hele|gehele|geheel|lump sum|vast bedrag|fixed (?:price|fee)|forfait|whole|entire|all[- ]in|aanneemsom"
    r"|compleet|complete|overall)\b",
    re.IGNORECASE,
)
_NOT_QUOTE = re.compile(r"\b(factuur|invoice|bonnetje|kassabon|receipt|betaald|paid)\b", re.IGNORECASE)
_QUOTE_WORDS = re.compile(r"\b(offerte|prijsopgave|quote|quotation)\b", re.IGNORECASE)
_ISO = r"(\d{4}-\d{2}-\d{2})"
_QUOTE_DATE = re.compile(rf"\b(offerte|quote|datum|date|dated)\b[^\n\d]{{0,20}}{_ISO}", re.IGNORECASE)
_WORK_DATE = re.compile(rf"\b(uitvoering|werkdatum|work date|werk|work|start)\b[^\n\d]{{0,25}}{_ISO}", re.IGNORECASE)
_RELATIVE = (
    (r"\bovermorgen\b|\bday after tomorrow\b", 2),
    (r"\bmorgen\b|\btomorrow\b", 1),
    (r"\bvandaag\b|\btoday\b", 0),
)
_CENT = Decimal("0.01")


def _blocks(prompt: str, tag: str) -> list[str]:
    return re.findall(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.S)


def _number(raw: str) -> Decimal | None:
    raw = raw.rstrip(".,")
    if "." in raw and "," in raw:
        decimal_sep = "." if raw.rfind(".") > raw.rfind(",") else ","
        raw = raw.replace("," if decimal_sep == "." else ".", "").replace(decimal_sep, ".")
    elif raw.count(".") + raw.count(",") == 1 and len(raw) - 1 - max(raw.rfind("."), raw.rfind(",")) in (1, 2):
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(".", "").replace(",", "")
    try:
        value = Decimal(raw).quantize(_CENT)
    except ArithmeticError:
        return None
    return value if 0 < value < Decimal(10) ** 9 else None


def _amounts(text: str) -> list[tuple[Decimal, str]]:
    found: list[tuple[Decimal, str]] = []
    for m in _AMOUNT.finditer(text):
        value = _number(m.group("a") or m.group("b"))
        if value is not None:
            found.append((value, _CURRENCY[(m.group("pre") or m.group("post")).lower()]))
    return found


def _money(value: Decimal, currency: str) -> dict[str, str]:
    return {"amount": f"{value:.2f}", "currency": currency}


def _vat(text: str) -> bool | None:
    excl, incl = bool(_EXCL.search(text)), bool(_INCL.search(text))
    return False if excl and not incl else True if incl and not excl else None


def _description(text: str) -> str:
    text = _TIMES.sub(" ", _PER.sub(" ", _QTY.sub(" ", _AMOUNT.sub(" ", text))))
    text = _EXCL.sub(" ", _INCL.sub(" ", text))
    words = re.sub(r"[^\w\s%&/-]", " ", text).split()
    return " ".join(w for w in words if w not in ("-", "/", "per", "x", "à"))[:200] or "Line item"


def _quantity(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw.replace(",", ".")).quantize(Decimal("0.001"))
    except ArithmeticError:
        return None
    return value if 0 < value <= MAX_QUANTITY else None


def _item(text: str, doc_vat: bool | None) -> dict[str, object] | None:
    """One quote line from a text line with an amount, or None when its numbers do not make a valid line."""
    amounts = _amounts(text)
    bare = _AMOUNT.sub(" ", text)
    qty_m, times, per = _QTY.search(bare), _TIMES.search(bare), _PER.search(bare)
    per_unit = _PER_UNIT.search(bare)
    quantity = (
        _quantity(qty_m.group(1)) if qty_m else _quantity(times.group(1) or times.group(2)) if times else Decimal(1)
    )
    unit = _UNITS[qty_m.group(2).lower()] if qty_m else "piece" if times else "job"
    if per_unit:
        unit = _UNITS[per_unit.group(1).lower()]
    value, currency = amounts[-1]
    unit_price: dict[str, str] | None = None
    if quantity is None:
        return None
    if len(amounts) >= 2 or times or per:
        price = amounts[0][0]
        unit_price = _money(price, amounts[0][1])
        value, currency = amounts[-1] if len(amounts) >= 2 else (price * quantity, currency)
        value = value.quantize(_CENT)
    own = _vat(text)
    return {
        "description": _description(text), "quantity": f"{quantity:.3f}", "unit": unit, "unit_price": unit_price,
        "amount": _money(value, currency), "vat_included": doc_vat if own is None else own,
    }  # fmt: skip


def _dates(text: str, received_on: date | None) -> tuple[str | None, str | None]:
    def iso(found: re.Match[str] | None) -> str | None:
        try:
            return date.fromisoformat(found.group(2)).isoformat() if found else None
        except ValueError:
            return None

    work = iso(_WORK_DATE.search(text))
    if work is None and received_on is not None:
        for pattern, days in _RELATIVE:
            if re.search(pattern, text, re.IGNORECASE):
                return iso(_QUOTE_DATE.search(text)), (received_on + timedelta(days=days)).isoformat()
    return iso(_QUOTE_DATE.search(text)), work


def fake_quote_reader(prompt: str) -> dict[str, object]:
    kept = [
        ln.strip()
        for tag in ("data", "message", "document")
        for block in _blocks(prompt, tag)
        for part in block.splitlines()
        for ln in part.split(";")
        if ln.strip() and not _SKIP.search(ln)
    ]
    text = "\n".join(kept)
    priced = [ln for ln in kept if _amounts(ln)]
    refused = _NOT_QUOTE.search(text) and not _QUOTE_WORDS.search(text)
    if not priced or refused:
        return {"lines": [], "total": None, "quote_date": None, "work_date": None, "vat_included": None,
                "is_quote": False}  # fmt: skip
    doc_vat = _vat(text)
    totals = [ln for ln in priced if _TOTAL.search(ln) or _LUMP.search(ln)]
    items = [i for ln in priced if ln not in totals and (i := _item(ln, doc_vat)) is not None]
    total = _amounts(totals[-1])[-1] if totals else None
    received = re.search(r"<received_on>(\d{4}-\d{2}-\d{2})</received_on>", prompt)
    quote_date, work_date = _dates(text, date.fromisoformat(received.group(1)) if received else None)
    return {
        "lines": items[:MAX_QUOTE_LINES], "total": _money(*total) if total else None, "quote_date": quote_date,
        "work_date": work_date, "vat_included": doc_vat, "is_quote": True,
    }  # fmt: skip


_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n")


def fake_job_items(prompt: str) -> dict[str, object]:
    """One item per sentence naming a known maintenance term (`ITEM_TERMS`), one per kind of work, at most 10."""
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for block in [*_blocks(prompt, "case"), *_blocks(prompt, "message")]:
        for sentence in _SENTENCES.split(block):
            key = normalise_item_key(sentence)
            if key not in ITEM_TERMS or key in seen or len(items) >= MAX_JOB_ITEMS:
                continue
            seen.add(key)
            qty = _QTY.search(sentence)
            quantity = _quantity(qty.group(1)) if qty else None
            unit = _UNITS[qty.group(2).lower()] if qty and quantity else "job"
            items.append(
                {"description": sentence.strip()[:200], "quantity": f"{quantity or Decimal(1):.3f}", "unit": unit}
            )
    return {"items": items}
