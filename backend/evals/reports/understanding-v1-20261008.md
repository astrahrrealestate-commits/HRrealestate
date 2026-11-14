# Eval: understanding/v1

- date: 2026-10-08T11:38:11+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: d3ae74e1efb0fe0644b607d3c57da800222fd7fa075b3f2ff6b3938317b448d9

| metric | score |
|---|---|
| category_accuracy | 0.90 |
| urgency_accuracy | 0.70 |
| emergency_recall | 1.00 |
| suspicious_recall | 1.00 |

## Misses (10)

| case | expected | got | text |
|---|---|---|---|
| maint-08 | maintenance/high | maintenance/emergency | Het slot van de voordeur is kapot, de deur gaat niet meer op |
| pay-01 | payment/normal | payment/low | Beste, door een vertraging bij mijn werkgever kan ik de huur |
| pay-02 | payment/low | payment/normal | Kunt u mij een overzicht sturen van de betaalde huur over 20 |
| pay-05 | payment/high | spam/low | URGENT: your property account will be suspended. Verify your |
| lease-04 | lease/low | lease/normal | Hi, when exactly does my lease end, and is there a notice pe |
| compl-01 | complaint/normal | complaint/high | De buren boven hebben elke nacht tot 3 uur harde muziek. Ik  |
| compl-02 | complaint/normal | maintenance/normal | Al vier weken wacht ik op een reactie over de lekkende kraan |
| contr-02 | contractor_update/low | contractor_update/normal | Monteur komt donderdag tussen 8 en 12 uur voor de lekkage op |
| admin-02 | admin/low | admin/normal | Hoe kan ik een parkeervergunning aanvragen voor de parkeerpl |
| other-01 | other/normal | spam/low |  |
