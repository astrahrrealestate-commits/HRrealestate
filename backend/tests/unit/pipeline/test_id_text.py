"""Identity documents recognised by their text (M13 security review): a file name proves nothing."""

import pytest

from app.pipeline.document_policy import looks_like_id_text

MRZ = "P<NLDDE<VRIES<<ANOUK<<<<<<<<<<<<<<<<<<<<<<<<\nNX1234567<8NLD9001019F3001014123456782<<<<<54"


@pytest.mark.parametrize(
    "text",
    [
        MRZ,
        "KONINKRIJK DER NEDERLANDEN\nPASPOORT / PASSPORT\nNationaliteit Nederlandse\nGeboortedatum 01 01 1990",
        "IDENTITEITSKAART\nIdentity card\nDocumentnummer NX1234567\nGeldig tot 01 01 2030",
        "Rijbewijs\nDriving licence\n4d. 1234567890",
        "Burgerservicenummer: 123456782",
    ],
)
def test_identity_documents_are_recognised_by_their_text(text: str) -> None:
    assert looks_like_id_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "Offerte stucwerk hal 40 m2 a EUR 120",
        "Huurovereenkomst artikel 7: huisdieren alleen met toestemming. Huurder legitimeert zich bij ondertekening.",
        "Factuur 2026-118 Geboortedatum niet nodig",
    ],
)
def test_ordinary_papers_are_not_identity_documents(text: str) -> None:
    assert not looks_like_id_text(text)
