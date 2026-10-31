"""The checklist framework as data. The default is a Dutch residential screening checklist (`nl-residential-v1`);
`dd_framework_path` points at a JSON file in the same shape to replace it, so the client's own framework can drive
the checklist without code changes."""

from decimal import Decimal
from pathlib import Path
from typing import Self

from pydantic import model_validator

from app.contracts.common import Contract
from app.contracts.diligence import DDDocKind, DDField, DDPropertyKind
from app.contracts.diligence_report import RequirementSeverity

K = DDDocKind
P = DDPropertyKind
S = RequirementSeverity


class Condition(Contract):
    """A requirement that applies only when a fact says so: text contains `contains`, or number is below `below`.
    `if_unknown`: whether it applies while the fact is not stated anywhere (safe default: it does)."""

    field: DDField
    contains: str | None
    below: Decimal | None
    if_unknown: bool


class Requirement(Contract):
    key: str
    label: str
    property_kinds: list[DDPropertyKind]
    accepts: list[DDDocKind]
    severity: RequirementSeverity
    why: str
    max_age_days: int | None
    when: Condition | None


class Thresholds(Contract):
    min_confidence: float
    leasehold_high_years: int
    leasehold_medium_years: int
    old_building_year: int
    asbestos_year: int
    tenancy_warn_days: int
    energy_high: list[str]
    energy_medium: list[str]


class Framework(Contract):
    version: str
    requirements: list[Requirement]
    authority: dict[DDDocKind, int]  # higher is more authoritative: brochure 1, advisory 2, legal 3
    field_tolerance: dict[DDField, Decimal]  # relative tolerance for numbers; 0 means exact
    thresholds: Thresholds

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        keys = [r.key for r in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement keys must be unique")
        return self

    def tolerance(self, field: DDField) -> Decimal:
        return self.field_tolerance.get(field, Decimal(0))


def _req(
    key: str, label: str, kinds: list[P], accepts: list[K], severity: S, why: str,
    max_age_days: int | None = None, when: Condition | None = None,
) -> Requirement:  # fmt: skip
    return Requirement(
        key=key, label=label, property_kinds=kinds, accepts=accepts, severity=severity, why=why,
        max_age_days=max_age_days, when=when,
    )  # fmt: skip


_APARTMENT = [P.apartment, P.tenanted_investment]
_ALL = [P.apartment, P.house, P.tenanted_investment]
_BEFORE_1994 = Condition(field=DDField.year_built, contains=None, below=Decimal(1994), if_unknown=True)
_LEASEHOLD = Condition(field=DDField.ownership_type, contains="leasehold", below=None, if_unknown=False)

_REQUIREMENTS = [
    _req("title", "Deed of title or purchase agreement", _ALL, [K.deed_of_title, K.purchase_agreement], S.critical,
         "Shows who owns the property and on what terms it is sold."),
    _req("kadaster", "Kadaster extract", _ALL, [K.kadaster_extract], S.critical,
         "Shows registered ownership, mortgages and encumbrances."),
    _req("vve_rules", "VvE split deed and rules", _APARTMENT, [K.vve_rules], S.critical,
         "Defines what the owner may do and owes to the owners' association."),
    _req("vve_budget", "VvE budget or annual accounts", _APARTMENT, [K.vve_budget], S.important,
         "Shows the monthly contribution and the association's finances."),
    _req("vve_minutes", "VvE meeting minutes (last 18 months)", _APARTMENT, [K.vve_minutes], S.important,
         "Shows disputes, planned works and special levies.", max_age_days=548),
    _req("vve_mjop", "VvE multi-year maintenance plan", _APARTMENT, [K.vve_maintenance_plan], S.important,
         "Shows upcoming building costs and whether the reserve covers them."),
    _req("energy_label", "Energy label (valid 10 years)", _ALL, [K.energy_label], S.important,
         "Required at sale; low labels cost money to improve.", max_age_days=3650),
    _req("house_survey", "Building survey", [P.house], [K.building_survey], S.important,
         "Shows structural and maintenance defects."),
    _req("survey", "Building survey", _APARTMENT, [K.building_survey], S.nice,
         "Shows structural and maintenance defects."),
    _req("asbestos", "Asbestos report (built before 1994)", _ALL, [K.asbestos_report], S.important,
         "Asbestos was used in building until 1994.", when=_BEFORE_1994),
    _req("ground_lease", "Ground lease papers (erfpacht)", _ALL, [K.ground_lease], S.critical,
         "A leasehold has a fee, an end date and renewal terms that change the value.", when=_LEASEHOLD),
    _req("permits", "Permits for extensions or changes", [P.house], [K.permit], S.nice,
         "Unpermitted building work can force removal."),
    _req("leases", "Lease agreements of the tenants", [P.tenanted_investment], [K.lease_agreement], S.critical,
         "Define the rent, term and tenant rights that come with the property."),
    _req("rent_roll", "Rent roll", [P.tenanted_investment], [K.rent_roll], S.important,
         "Shows income per unit and arrears."),
    _req("brochure", "Sales brochure", _ALL, [K.brochure], S.nice,
         "Needed to compare what is advertised with the legal papers."),
]  # fmt: skip

_AUTHORITY = {
    K.brochure: 1, K.other: 1,
    K.vve_minutes: 2, K.vve_budget: 2, K.vve_maintenance_plan: 2, K.energy_label: 2, K.building_survey: 2,
    K.asbestos_report: 2, K.valuation: 2, K.insurance: 2, K.rent_roll: 2,
    K.purchase_agreement: 3, K.deed_of_title: 3, K.kadaster_extract: 3, K.vve_rules: 3, K.ground_lease: 3,
    K.permit: 3, K.lease_agreement: 3,
}  # fmt: skip

_TOLERANCE = {
    DDField.living_area_m2: Decimal("0.02"), DDField.plot_area_m2: Decimal("0.02"),
    DDField.ground_lease_fee: Decimal("0.01"), DDField.vve_monthly_contribution: Decimal("0.05"),
    DDField.monthly_rent: Decimal("0.02"),
}  # fmt: skip

_THRESHOLDS = Thresholds(
    min_confidence=0.5, leasehold_high_years=15, leasehold_medium_years=30, old_building_year=1945, asbestos_year=1994,
    tenancy_warn_days=365, energy_high=["F", "G"], energy_medium=["E"],
)  # fmt: skip


def default_framework() -> Framework:
    return Framework(
        version="nl-residential-v1", requirements=_REQUIREMENTS, authority=_AUTHORITY,
        field_tolerance=_TOLERANCE, thresholds=_THRESHOLDS,
    )  # fmt: skip


def load_framework(path: Path | None) -> Framework:
    """The framework in the JSON file at `path`, else the default. An invalid file raises (a bad checklist must not
    silently fall back to the default)."""
    if path is None:
        return default_framework()
    return Framework.model_validate_json(path.read_text(encoding="utf-8"))
