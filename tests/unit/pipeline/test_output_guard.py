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
