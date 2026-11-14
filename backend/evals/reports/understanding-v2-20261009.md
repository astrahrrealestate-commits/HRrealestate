# Eval: understanding/v2

- date: 2026-10-09T06:22:10+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: 9a0728a081299ad7f88e4956e924b5f813ddd90b5f55d108e172cdbc2de10cb9

| metric | score |
|---|---|
| category_accuracy | 0.91 |
| urgency_accuracy | 0.74 |
| emergency_recall | 1.00 |
| suspicious_recall | 1.00 |
| reply_flag_accuracy | 0.94 |
| needless_draft_rate | 0.10 |
| missed_reply_rate | 0.04 |

## Misses (11)

| case | expected | got | text |
|---|---|---|---|
| maint-06 | maintenance/low/reply=True | maintenance/normal/reply=True | De deurbel doet het niet meer. Geen haast, maar wel handig a |
| pay-02 | payment/low/reply=True | payment/normal/reply=True | Kunt u mij een overzicht sturen van de betaalde huur over 20 |
| pay-05 | payment/high/reply=False | spam/emergency/reply=False | URGENT: your property account will be suspended. Verify your |
| lease-04 | lease/low/reply=True | lease/normal/reply=True | Hi, when exactly does my lease end, and is there a notice pe |
| compl-01 | complaint/normal/reply=True | complaint/high/reply=True | De buren boven hebben elke nacht tot 3 uur harde muziek. Ik  |
| compl-02 | complaint/normal/reply=True | maintenance/high/reply=True | Al vier weken wacht ik op een reactie over de lekkende kraan |
| contr-02 | contractor_update/low/reply=False | contractor_update/normal/reply=False | Monteur komt donderdag tussen 8 en 12 uur voor de lekkage op |
| contr-03 | contractor_update/low/reply=False | contractor_update/low/reply=True | The roof repair at Dorpsstraat 7 is finished. Invoice will f |
| admin-01 | admin/normal/reply=True | maintenance/normal/reply=True | Ik ben mijn sleutel van de fietsenberging kwijt. Kan ik een  |
| admin-02 | admin/low/reply=True | admin/normal/reply=True | Hoe kan ik een parkeervergunning aanvragen voor de parkeerpl |
| other-01 | other/normal/reply=True | other/low/reply=False |  |
