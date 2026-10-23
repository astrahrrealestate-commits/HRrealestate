from app.pipeline.output_guard import unverified


def test_invented_link_iban_and_phone_are_found() -> None:
    draft = "Betaal op NL91 ABNA 0417 1643 00 of bel +31 6 12345678, zie https://pay.example.com/x"
    found = unverified(draft, "Wanneer kan de loodgieter komen?")
    assert len(found) == 3


def test_things_the_sender_wrote_are_allowed() -> None:
    source = "Mijn nummer is 06-12345678 en ik zag https://foto.example.com/a.jpg"
    draft = "Dank, ik bel u op 06 12345678. De foto op https://foto.example.com/a.jpg is ontvangen."
    assert unverified(draft, source) == []


def test_plain_text_is_clean() -> None:
    assert unverified("Er komt morgen iemand langs om 10:00.", "Het lekt") == []


def test_dates_times_and_amounts_are_not_phone_numbers() -> None:
    for draft in (
        "Afspraak 12-10-2026 om 10:00",
        "Van 12-10-2026 tot 14-10-2026",
        "12 10 2026",
        "2026-10-12 14:30",
        "Bedrag 1.250,00 en 1.300,00",
        "op 14-10-2026 09.30 uur",
        "tussen 08.00 - 12.00 uur",
        "14 oktober 2026, 09.30 - 11.30",
        "dinsdag 14/10 13.00 - 17.00 uur",
    ):
        assert unverified(draft, "x") == [], draft


def test_real_phone_numbers_are_still_found() -> None:
    assert len(unverified("Bel 020 1234567", "x")) == 1
    assert len(unverified("Bel 06-12345678", "x")) == 1
    assert len(unverified("Bel 06 12 34 56 78", "x")) == 1
    assert len(unverified("Bel +31 6 12345678", "x")) == 1
    assert len(unverified("Bel (020) 123 45 67", "x")) == 1
