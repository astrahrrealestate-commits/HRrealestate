"""Quote verification: a claim or flag whose words are not in the document is dropped and counted."""

from app.contracts.diligence import DDField
from app.diligence.verify import verify_read
from tests.unit.diligence.builders import doc, flag, num

TEXT = "Verkoopbrochure\nWoonoppervlakte   85 m2\nBouwjaar 1965\n  Er is een geschil met de VvE over het dak."


def _read(*claims, flags=()):  # type: ignore[no-untyped-def]
    from app.contracts.diligence import DDDocKind

    return doc(DDDocKind.brochure, *claims, flags=flags).read


def test_quote_found_after_whitespace_and_case_normalisation() -> None:
    read = _read(num(DDField.living_area_m2, "85", quote="woonoppervlakte 85 m2"))
    assert read is not None
    kept, dropped = verify_read(read, TEXT)
    assert len(kept.claims) == 1
    assert dropped == 0


def test_claim_with_invented_quote_is_dropped_and_counted() -> None:
    read = _read(
        num(DDField.living_area_m2, "85", quote="Woonoppervlakte 85 m2"),
        num(DDField.year_built, "1975", "Bouwjaar 1975"),
    )
    assert read is not None
    kept, dropped = verify_read(read, TEXT)
    assert [c.field for c in kept.claims] == [DDField.living_area_m2]
    assert dropped == 1


def test_flag_is_verified_like_a_claim() -> None:
    good = flag(quote="geschil met de VvE")
    bad = flag(quote="asbest in het dak")
    read = _read(flags=(good, bad))
    assert read is not None
    kept, dropped = verify_read(read, TEXT)
    assert kept.flags == [good]
    assert dropped == 1


def test_empty_text_drops_everything() -> None:
    read = _read(num(DDField.living_area_m2, "85"))
    assert read is not None
    kept, dropped = verify_read(read, "")
    assert kept.claims == []
    assert dropped == 1


def test_a_number_claim_must_appear_in_its_quote() -> None:
    from app.contracts.diligence import DDDocKind

    good = num(DDField.year_built, "1965", "Bouwjaar 1965")
    wrong = num(DDField.year_built, "2024", "Bouwjaar 1965")
    short = num(DDField.year_built, "1965", "65")
    read = doc(DDDocKind.brochure, good, wrong, short).read
    assert read is not None
    kept, dropped = verify_read(read, "Verkoopbrochure\nBouwjaar 1965 en 65")
    assert kept.claims == [good]
    assert dropped == 2


def test_text_and_date_claims_must_be_supported_by_their_quote() -> None:
    from datetime import date

    from app.contracts.diligence import DDDocKind
    from tests.unit.diligence.builders import day, txt

    text = "Verkoopbrochure\nEnergielabel: B\nEinddatum erfpacht: 2045-01-01"
    ok = [
        txt(DDField.energy_label, "B", "Energielabel: B"),
        day(DDField.ground_lease_end, date(2045, 1, 1), "Einddatum erfpacht: 2045-01-01"),
    ]
    bad = [
        txt(DDField.energy_label, "A", "Energielabel: B"),
        day(DDField.ground_lease_end, date(2060, 1, 1), "Einddatum erfpacht: 2045-01-01"),
    ]
    read = doc(DDDocKind.brochure, *ok, *bad).read
    assert read is not None
    kept, dropped = verify_read(read, text)
    assert kept.claims == ok
    assert dropped == 2


def test_a_document_kind_with_no_supporting_words_is_not_trusted() -> None:
    from app.contracts.diligence import DDDocKind

    read = doc(DDDocKind.deed_of_title, confidence=0.9).read
    assert read is not None
    kept, _ = verify_read(read, "Leuke woning met tuin, vraagprijs op aanvraag.")
    assert kept.confidence <= 0.4
    honest = doc(DDDocKind.deed_of_title, confidence=0.9).read
    assert honest is not None
    assert verify_read(honest, "Akte van levering\nvan de woning")[0].confidence == 0.9
