# BRIXX data audit: what the platform expects vs what BRIXX sends

Measured on the stage mirror, 2026-11-16 (hrrealestate environment, the production API token). Counts are rows with a
non-empty value. This page decides what the dashboard may show: a field BRIXX does not send is not shown, never
filled in.

## Personal data is redacted for this API token

`PRG_RELATIE` (122 relaties) arrives with **every person field empty**: `WEERGAVENAAM`, `VOORNAAM`, `VOORLETTERS`,
`TUSSENVOEGSELS`, `ACHTERNAAM`, `EMAIL`, `TELEFOON1/2`, the address and `GEBOORTEDATUM` are 0/122.
`PRG_RELATIECONTACT` is empty. Wherever another table points at a relatie, BRIXX sends the display value
`"--redacted"` (`PRG_CONTRACT.$EERSTERELATIEID` 66/66, `PRG_CONTRACTRELATIE.$PRG_RELATIEID` 104/104,
`TST_TICKET.$PRG_RELATIEID`). Only organisations keep a name (`ORGANISATIENM`, 11) and every relatie keeps its
number (`RELATIENRSTR`, e.g. `R-00042`, 122/122).

So tenant **full names, email and phone cannot come from BRIXX until the API token is allowed personal data** (a
setting on the token in BRIXX, by the client's BRIXX administrator). Until then a person is shown as
`Relatie R-00042` (BRIXX's own relation number, searchable in BRIXX). Nothing else changes when BRIXX starts sending
names: the mapper already builds the full name from `VOORNAAM` / `VOORLETTERS` + `TUSSENVOEGSELS` + `ACHTERNAAM`, and
the next sync replaces the number label. `"--redacted"` is never shown as a value (`columns.REDACTED`). Phone and
email can still appear when a tenant writes on WhatsApp or Gmail (channel identities).

## Table by table

| BRIXX table | Rows | The platform reads | Sent | Not sent (empty) |
|---|---|---|---|---|
| PRG_RELATIE | 122 | name, contact, address | `RELATIENRSTR` 122, `ORGANISATIENM` 11 | all person names, email, phones, address, birth date |
| PRG_OBJECT (building) | 59 | name, address | `WEERGAVENAAM(2)` 59, street/number/postcode/city 59, `HUISLETTER` 48 | `OBJECTNM` (1) |
| PRG_SUBOBJECT (unit) | 59 | name, address, area, floor | `WEERGAVENAAM2` 59 ("Henry Dunantweg 5 A"), address 59, `VVO` 55 | `BOUWLAAGNR` (floor) 0, `BVO` 0, `SUBOBJECTNM` 1 |
| PRG_CONTRACT | 66 | tenant, period, deposit | `EERSTERELATIEID` 66, `INGANGSDATUM` 66, `WAARBORGSOM` 64, `MEDERELATIES` 14 (free text) | `EINDDATUM` only 17 (49 open-ended), every name field |
| PRG_CONTRACTVHE | 89 | unit of a contract | all 89 | `EINDDATUM` 0 |
| PRG_CONTRACTRELATIE | 104 | tenant + co-tenants | all 104 (`VOLGNR` 1 = tenant) | — |
| FIN_BETAALREGEL | 205 | monthly rent | amount, component, period 205 | — |
| FIN_FACTUUR / FIN_BETALING | 2648 / 1130 | Money tab | contract, plan date, amount; payments linked | `FACTUURNR` 1188/2648 |
| TST_TICKET | 8 | Maintenance | title, status, urgency, unit, contractor 8; tenant 7 | `DATUMGESLOTEN` 0 |
| TST_TICKETBERICHT | 52 | ticket history | text 41 | `ACTIEDATUM` 0 (creation time used) |
| PRG_DOCUMENT | 3309 | documents | metadata rows | `OMSCHRIJVING` 0; no relatie/contract link in the mirror |

## Name and column mismatches handled

| Expected (API docs) | Real environment | Platform |
|---|---|---|
| `PRG_VHE` | `PRG_SUBOBJECT` | `columns.VHE` |
| `PRG_CONTRACT.PRG_RELATIEID` | absent: `EERSTERELATIEID` + `PRG_CONTRACTRELATIE` | `parties.py` |
| unit name `VHENR` | internal NUMERIC id (`100000000100001`) | `WEERGAVENAAM2` first |
| `PLAATSNM`, `HUISNRTOEV` | `WOONPLAATSNM`, `HUISLETTER` / `HUISNUMMERTOEV` | both read |
| `TELEFOONNR`, `MOBIELNR` | `TELEFOON1`, `TELEFOON2` | both read |
| Oracle types (NUMBER) | Postgres types (BIGINT, NUMERIC) | migration 0046 |

## Removed from the dashboard (BRIXX does not send it, nothing else knows it)

- Unit **floor** and **lockbox PIN** (Properties): `BOUWLAAGNR` is empty and BRIXX has no lockbox field.
- Tenant **"iDIN verified"** badge and **residential address** (Tenants): no BRIXX source.
- Every hard-coded fallback: rent € 1650 / € 2.450, deposit € 3300 / € 4.900, area 75 m², lease 01-01-2025 to
  31-12-2026, "Keizersgracht 42" addresses, a sample heating ticket, placeholder contractor phone and email.
- "Rent up to date" when no rent record exists (now "No rent records yet").

Shown from BRIXX instead: rent (current `FIN_BETAALREGEL` "Huur ..." lines), deposit (`WAARBORGSOM`), living area
(`VVO`), lease start, lease end or "Open-ended", co-tenants, BRIXX tickets with their history.
