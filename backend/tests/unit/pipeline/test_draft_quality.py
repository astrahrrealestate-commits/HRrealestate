"""A generic draft is never offered (M13 T9): Harjot's standard forbids empty acknowledgements."""

import pytest

from app.pipeline.draft_quality import GENERIC_PHRASES, is_generic, usable_variants

SIGN = "\n\nMet vriendelijke groet,\nHarjot"


@pytest.mark.parametrize(
    "text",
    [
        "Beste Anouk,\n\nDank voor uw bericht. Wij hebben het in goede orde ontvangen." + SIGN,
        "Beste,\n\nWij nemen uw bericht in behandeling en komen er zo snel mogelijk op terug." + SIGN,
        "Geachte heer De Vries,\n\nUw melding is ontvangen. Wij nemen zo spoedig mogelijk contact met u op." + SIGN,
        "Dear Mr Smith,\n\nThank you for your message. We have received it and will get back to you shortly.\n\nBest "
        "regards,\nHarjot",
        "Hi Tom, thanks for reaching out. I am looking into this and will follow up as soon as I can.",
        "Beste,\n\nBedankt voor uw e-mail. Ik kijk ernaar en laat het u weten." + SIGN,
        "Beste,\n\nWij hebben uw melding over de lekkage in de badkamer van uw woning aan de Singel in goede orde "
        "ontvangen en komen er zo snel mogelijk op terug." + SIGN,
    ],
)
def test_is_generic_on_dutch_and_english_acknowledgements(text: str) -> None:
    assert is_generic(text)


@pytest.mark.parametrize(
    "text",
    [
        "Beste Anouk,\n\nDank voor uw bericht. De monteur komt donderdag 9 uur; laat u hem binnen?" + SIGN,
        "Beste Anouk,\n\nDank voor uw bericht. Uw borg van EUR 1.900 storten wij uiterlijk 1 december terug." + SIGN,
        "Geachte heer Jansen,\n\nDank voor uw offerte. Post 3 (EUR 1.200 voor stucwerk) ligt boven de markt; wij "
        "bieden EUR 950." + SIGN,
        "Dear Mr Smith,\n\nThanks for your message. Which unit is this about, and since when is the heating off?",
        "Beste,\n\nWij gaan akkoord met uw voorstel om de keuken in week 3 te vervangen." + SIGN,
    ],
)
def test_is_generic_false_for_a_substantive_reply_that_starts_with_thanks(text: str) -> None:
    assert not is_generic(text)


def test_an_empty_draft_is_generic() -> None:
    assert is_generic("")
    assert is_generic("Met vriendelijke groet,\nHarjot")


def test_usable_variants_keeps_the_substantive_ones_in_order() -> None:
    good_a = "Beste,\n\nWanneer bent u thuis?" + SIGN
    good_b = "Beste,\n\nDe monteur komt dinsdag." + SIGN
    bad = "Beste,\n\nDank voor uw bericht, wij komen erop terug." + SIGN
    assert usable_variants([bad, good_a, good_b]) == [good_a, good_b]


def test_generic_phrases_live_only_here() -> None:
    assert len(GENERIC_PHRASES) >= 8
