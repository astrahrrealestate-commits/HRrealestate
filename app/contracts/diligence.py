"""Due Diligence Lite contracts: what the `dd_reader` agent returns for one document, and the shared vocabularies.

`DDDocRead` is an LLM `output_type`, so it follows the strict-schema rules in `common.py` (no defaults, no length
keywords on strings). The model only reads text into typed, quoted claims: comparing, ranking and rating are code.
`DDDocKind` and `DDField` values are stored in `dd_document_reads` and never change.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, WithJsonSchema, model_validator

from app.contracts.common import Contract, NonBlankStr, max_len

MAX_CLAIMS = 25
MAX_FLAGS = 6

Number = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    WithJsonSchema({"type": "string", "pattern": r"^[0-9]{1,12}(\.[0-9]{1,2})?$"}),
]


class DDPropertyKind(StrEnum):
    apartment = "apartment"
    house = "house"
    tenanted_investment = "tenanted_investment"


class DDDocKind(StrEnum):
    brochure = "brochure"  # verkoopbrochure, listing text: marketing
    purchase_agreement = "purchase_agreement"  # koopovereenkomst, draft deed
    deed_of_title = "deed_of_title"  # eigendomsakte, akte van levering
    kadaster_extract = "kadaster_extract"
    vve_rules = "vve_rules"  # splitsingsakte, reglement, huishoudelijk reglement
    vve_minutes = "vve_minutes"  # notulen ALV
    vve_budget = "vve_budget"  # begroting, jaarrekening
    vve_maintenance_plan = "vve_maintenance_plan"  # MJOP
    ground_lease = "ground_lease"  # erfpachtakte, erfpachtvoorwaarden
    energy_label = "energy_label"
    building_survey = "building_survey"  # bouwkundig rapport
    asbestos_report = "asbestos_report"
    valuation = "valuation"  # taxatierapport, WOZ
    permit = "permit"  # omgevingsvergunning, bestemmingsplan extract
    insurance = "insurance"
    lease_agreement = "lease_agreement"  # huurovereenkomst of the property under review
    rent_roll = "rent_roll"
    other = "other"


class DDField(StrEnum):
    price = "price"  # EUR
    living_area_m2 = "living_area_m2"
    plot_area_m2 = "plot_area_m2"
    year_built = "year_built"
    energy_label = "energy_label"  # A++++ .. G
    ownership_type = "ownership_type"  # freehold | leasehold | apartment_right
    ground_lease_end = "ground_lease_end"
    ground_lease_fee = "ground_lease_fee"  # EUR per year
    vve_monthly_contribution = "vve_monthly_contribution"  # EUR
    address = "address"
    monthly_rent = "monthly_rent"  # EUR
    tenancy_end = "tenancy_end"
    asbestos = "asbestos"  # present | absent


class ValueKind(StrEnum):
    number = "number"
    text = "text"
    day = "day"


FIELD_KIND: dict[DDField, ValueKind] = {
    DDField.price: ValueKind.number,
    DDField.living_area_m2: ValueKind.number,
    DDField.plot_area_m2: ValueKind.number,
    DDField.year_built: ValueKind.number,
    DDField.energy_label: ValueKind.text,
    DDField.ownership_type: ValueKind.text,
    DDField.ground_lease_end: ValueKind.day,
    DDField.ground_lease_fee: ValueKind.number,
    DDField.vve_monthly_contribution: ValueKind.number,
    DDField.address: ValueKind.text,
    DDField.monthly_rent: ValueKind.number,
    DDField.tenancy_end: ValueKind.day,
    DDField.asbestos: ValueKind.text,
}


class DDClaim(Contract):
    """One fact as the document states it, with the words it was read from. Exactly one value slot is filled, the
    one `FIELD_KIND` names for the field. Code checks the quote against the document text before the claim is used."""

    field: DDField
    number: Number | None
    text: Annotated[str, max_len(80)] | None
    day: date | None
    quote: Annotated[NonBlankStr, max_len(200)]

    @model_validator(mode="after")
    def _one_slot(self) -> Self:
        slots = {ValueKind.number: self.number, ValueKind.text: self.text, ValueKind.day: self.day}
        filled = [kind for kind, value in slots.items() if value is not None]
        if filled != [FIELD_KIND[self.field]]:
            raise ValueError(f"{self.field.value} takes exactly one {FIELD_KIND[self.field].value} value")
        if self.text is not None and not self.text.strip():
            raise ValueError("text value must not be blank")
        return self


class DDFlagCategory(StrEnum):
    legal = "legal"
    technical = "technical"
    financial = "financial"
    environmental = "environmental"
    ownership = "ownership"
    other = "other"


class DDFlag(Contract):
    """A red flag the document states in so many words (dispute, defect, arrears). Quoted; code rates it."""

    category: DDFlagCategory
    summary: Annotated[NonBlankStr, max_len(160)]
    quote: Annotated[NonBlankStr, max_len(240)]


class DDDocRead(Contract):
    """Output of the dd_reader agent for one document. OpenAI-strict (no defaults)."""

    doc_kind: DDDocKind
    title: Annotated[NonBlankStr, max_len(80)]
    document_date: date | None
    valid_until: date | None  # label expiry, policy end, quote validity: only when the document states it
    claims: Annotated[list[DDClaim], Field(max_length=MAX_CLAIMS)]
    flags: Annotated[list[DDFlag], Field(max_length=MAX_FLAGS)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
