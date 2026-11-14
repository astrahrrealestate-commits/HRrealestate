"""Mock Dutch portfolio for the agent tour: who lives where, what they write, which documents they send.

Everything is invented (names, numbers, addresses). Phone numbers use the reserved 0655500xxx range.
"""

from dataclasses import dataclass

from app.dev import fixtures as fx
from app.dev.mock_pdf import text_pdf


@dataclass(frozen=True)
class MockPerson:
    name: str
    kind: str  # PersonKind value
    phone: str
    trade: str | None = None
    unit: str | None = None  # label of the unit they rent
    email: str | None = None


UNITS = {
    "Keizersgracht 42-A": "Keizersgracht 42-A, 1015 CS Amsterdam",
    "Prinsengracht 118-B": "Prinsengracht 118-B, 1015 EA Amsterdam",
    "Lijnbaansgracht 9-C": "Lijnbaansgracht 9-C, 1017 PN Amsterdam",
}
PEOPLE = (
    MockPerson(
        "Sanne de Vries", "tenant", "+31655500101", unit="Keizersgracht 42-A", email="sanne.devries@example.test"
    ),
    MockPerson(
        "Mohammed El Amrani",
        "tenant",
        "+31655500102",
        unit="Prinsengracht 118-B",
        email="mohammed.elamrani@example.test",
    ),
    MockPerson("Lotte Jansen", "tenant", "+31655500103", unit="Lijnbaansgracht 9-C"),
    MockPerson(
        "Pieter Bakker Loodgieters",
        "contractor",
        "+31655500201",
        trade="loodgieter",
        email="info@bakker-loodgieters.example.test",
    ),
    MockPerson(
        "Elektro Visser", "contractor", "+31655500202", trade="elektricien", email="info@elektro-visser.example.test"
    ),
)
EMAIL = {p.name.split()[0]: p.email for p in PEOPLE if p.email}
PHONE = {p.name.split()[0]: p.phone for p in PEOPLE}
AGENT_QUESTIONS = (
    "Wat is er vandaag urgent en wat moet ik als eerste doen?",
    "Wat staat er in het huurcontract van Mohammed over de opzegtermijn en de huurverhoging?",
    "Hoeveel kost de offerte van Pieter Bakker voor de lekkage en wat zit erin?",
    "Welke documenten heb ik van Keizersgracht 42-A?",
    "Zet een verzoek uit bij een loodgieter voor de lekkage bij Keizersgracht 42-A.",
    "Hoeveel open zaken zijn er per categorie en welke wacht het langst op mij?",
)

QUOTE = (
    "Pieter Bakker Loodgieters B.V.  |  KvK 71234567  |  btw NL860123456B01",
    "",
    "OFFERTE 2026-117",
    "Datum: 3 november 2026   Geldig tot: 3 december 2026",
    "Opdracht: lekkage badkamerplafond, Keizersgracht 42-A, 1015 CS Amsterdam",
    "",
    "Werkzaamheden                                   Aantal   Prijs",
    "Lekdetectie en inspectie leidingwerk             1      EUR 95,00",
    "Vervangen koperen aanvoerleiding (2 m)           1     EUR 180,00",
    "Herstel plafond (stucwerk en schilderen)        1     EUR 160,00",
    "Voorrijkosten                                    1      EUR 45,00",
    "",
    "Totaal excl. btw: EUR 480,00",
    "Btw 21%: EUR 100,80",
    "Totaal incl. btw: EUR 580,80",
    "Uitvoering binnen 5 werkdagen na akkoord. Betaling binnen 14 dagen.",
)
INVOICE = (
    "Elektro Visser  |  KvK 62345678  |  btw NL851234567B01",
    "",
    "FACTUUR 2026-0931",
    "Factuurdatum: 28 oktober 2026   Vervaldatum: 11 november 2026",
    "Klant: Hausverwaltung Harjot Singh",
    "Object: Prinsengracht 118-B, 1015 EA Amsterdam",
    "",
    "Vervangen groepenkast en aardlekschakelaar     EUR 640,00",
    "Arbeid 4 uur a EUR 65,00                       EUR 260,00",
    "",
    "Totaal excl. btw: EUR 900,00",
    "Btw 21%: EUR 189,00",
    "Te betalen: EUR 1.089,00",
    "IBAN NL91 ABNA 0417 1643 00 t.n.v. Elektro Visser",
)
LEASE = (
    "HUUROVEREENKOMST WOONRUIMTE",
    "",
    "Verhuurder: Harjot Singh   Huurder: Mohammed El Amrani",
    "Woonruimte: Prinsengracht 118-B, 1015 EA Amsterdam",
    "Ingangsdatum: 1 maart 2025   Einddatum: 28 februari 2027 (bepaalde tijd)",
    "",
    "Artikel 1  Huurprijs: EUR 1.650,00 per maand, vooruit te betalen vóór de 1e van de maand.",
    "Artikel 2  Waarborgsom: EUR 3.300,00, terug te betalen binnen 14 dagen na oplevering.",
    "Artikel 3  Indexering: jaarlijks per 1 maart conform het CBS-consumentenprijsindexcijfer.",
    "Artikel 4  Opzegging: de huurder zegt schriftelijk op met een termijn van twee maanden",
    "           voor de einddatum; bij niet-tijdige opzegging loopt de overeenkomst door.",
    "Artikel 5  Onderhoud: klein dagelijks onderhoud komt voor rekening van de huurder.",
    "Artikel 6  Boete: bij te late betaling is de huurder een rente van 1% per maand verschuldigd.",
    "Artikel 7  Onderverhuur is niet toegestaan zonder schriftelijke toestemming van de verhuurder.",
    "",
    "Aldus overeengekomen te Amsterdam op 14 februari 2025.",
)
ENERGY_LABEL = (
    "ENERGIELABEL WOONGEBOUW - Rijksdienst voor Ondernemend Nederland",
    "",
    "Adres: Keizersgracht 42-A, 1015 CS Amsterdam",
    "Energielabel: D   Energie-index: 1,92",
    "Opgesteld op: 12 januari 2022   Geldig tot: 12 januari 2032",
    "Gebruiksoppervlakte: 86 m2   Bouwjaar: 1912",
    "Advies: vloerisolatie, HR++ glas, hybride warmtepomp.",
)
VVE_MINUTES = (
    "VvE KEIZERSGRACHT 40-44 - NOTULEN ALGEMENE LEDENVERGADERING 2026",
    "",
    "Datum: 21 september 2026   Aanwezig: 5 van 8 appartementsrechten",
    "1. Besloten: gevelrenovatie in 2027, geraamd EUR 410.000, bijdrage per appartement naar breukdeel.",
    "2. Reservefonds per 31 december 2025: EUR 86.400; verhoging maandbijdrage naar EUR 215.",
    "3. Eenmalige extra storting per appartement A t/m C: EUR 14.500 uiterlijk 1 maart 2027.",
    "4. Er loopt een geschil met de aannemer over lekkage in het dak (schade EUR 22.000).",
)
DOCUMENTS = {
    "offerte_2026-117.pdf": QUOTE,
    "factuur_2026-0931.pdf": INVOICE,
    "huurovereenkomst_prinsengracht-118-B.pdf": LEASE,
    "energielabel_keizersgracht-42-A.pdf": ENERGY_LABEL,
    "notulen_vve_2026.pdf": VVE_MINUTES,
}


def pdf(filename: str) -> fx.Attachment:
    return fx.Attachment(filename, "application/pdf", text_pdf(DOCUMENTS[filename]))
