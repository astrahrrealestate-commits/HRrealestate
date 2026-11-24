"""Who a thread's sender is, for the inbox labels: decided from the directory, never from message text."""

from app.api.inbox.sender_label import SenderKind, organisation_of, resolve_sender_label, unit_display
from app.db.enums import PersonKind


def _label(
    person_kind: PersonKind | None = None,
    *,
    trade: str | None = None,
    is_lease_party: bool = False,
    contractor_hint: bool = False,
):
    return resolve_sender_label(
        person_kind=person_kind, trade=trade, is_lease_party=is_lease_party, contractor_hint=contractor_hint
    )


def test_a_person_with_tenant_kind_is_a_tenant() -> None:
    label = _label(PersonKind.tenant)
    assert (label.kind, label.role_detail, label.audience) == (SenderKind.tenant, "Tenant", "tenants")


def test_a_lease_party_is_a_tenant_even_when_the_directory_kind_is_other() -> None:
    assert _label(PersonKind.other, is_lease_party=True).kind is SenderKind.tenant


def test_a_contractor_shows_the_trade() -> None:
    label = _label(PersonKind.contractor, trade="electrician")
    assert (label.kind, label.role_detail, label.audience) == (
        SenderKind.contractor,
        "Contractor · Electrician",
        "contractors",
    )


def test_a_contractor_without_a_trade_is_just_a_contractor() -> None:
    assert _label(PersonKind.contractor).role_detail == "Contractor"


def test_the_address_hint_marks_a_contractor_only_when_the_directory_knows_nothing_better() -> None:
    assert _label(None, contractor_hint=True).kind is SenderKind.contractor
    assert _label(PersonKind.other, contractor_hint=True).kind is SenderKind.contractor
    assert _label(PersonKind.tenant, contractor_hint=True).kind is SenderKind.tenant
    assert _label(None, is_lease_party=True, contractor_hint=True).kind is SenderKind.tenant


def test_an_unknown_sender_is_a_contact_never_a_tenant() -> None:
    for person_kind in (None, PersonKind.other, PersonKind.owner):
        label = _label(person_kind)
        assert (label.kind, label.role_detail, label.audience) == (SenderKind.contact, "Contact", "others")


def test_a_tenant_without_a_unit_still_shows_the_gap() -> None:
    assert unit_display(SenderKind.tenant, None, "anouk@example.nl") == "Unassigned Unit"


def test_a_tenant_shows_the_unit() -> None:
    assert unit_display(SenderKind.tenant, "Singel 5-A", "anouk@example.nl") == "Singel 5-A"


def test_a_contact_shows_the_property_named_in_the_thread() -> None:
    assert unit_display(SenderKind.contact, "Duinvlietstraat 42", "klaassen@pactadvocaten.nl") == "Duinvlietstraat 42"


def test_a_contact_without_a_property_shows_the_organisation_never_unassigned_unit() -> None:
    assert unit_display(SenderKind.contact, None, "klaassen@pactadvocaten.nl") == "pactadvocaten.nl"
    assert unit_display(SenderKind.contractor, None, "info@loodgieter.nl") == "loodgieter.nl"


def test_a_free_mail_address_is_not_an_organisation() -> None:
    assert organisation_of("someone@gmail.com") is None
    assert unit_display(SenderKind.contact, None, "someone@gmail.com") == "Unlisted contact"


def test_a_phone_number_or_blank_sender_has_no_organisation() -> None:
    assert organisation_of("+31612345678") is None
    assert organisation_of("") is None
    assert unit_display(SenderKind.contact, None, "+31612345678") == "Unlisted contact"


def test_the_organisation_ignores_case_and_surrounding_spaces() -> None:
    assert organisation_of("  Info@VVEGemak.NL ") == "vvegemak.nl"
