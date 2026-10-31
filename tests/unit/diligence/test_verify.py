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
