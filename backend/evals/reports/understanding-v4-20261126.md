# Eval: understanding/v4

- date: 2026-11-26T10:28:46+00:00
- model: google-gla:gemini-3.8-flash
- prompt sha256: 33a984568c7c148953a934ace239d2931218f725604e8f8a8bd4ff1d1bfe6ae6

| metric | score |
|---|---|
| category_accuracy | 0.92 |
| urgency_accuracy | 0.81 |
| emergency_recall | 1.00 |
| suspicious_recall | 1.00 |
| reply_flag_accuracy | 0.96 |
| needless_draft_rate | 0.00 |
| missed_reply_rate | 0.05 |
| sender_role_accuracy | 1.00 |
| needs_research_accuracy | 0.89 |
| role_on_noise_rate | 0.33 |

## Misses (15)

| case | expected | got | text |
|---|---|---|---|
| maint-01 | maintenance/high/reply=True/role=- | maintenance/emergency/reply=True/role=tenant | Goedemiddag, onder de gootsteen in de keuken lekt het al twe |
| maint-08 | maintenance/high/reply=True/role=- | maintenance/emergency/reply=True/role=tenant | Het slot van de voordeur is kapot, de deur gaat niet meer op |
| pay-02 | finance/low/reply=True/role=- | finance/normal/reply=True/role=tenant | Kunt u mij een overzicht sturen van de betaalde huur over 20 |
| pay-04 | finance/high/reply=True/role=- | finance/normal/reply=True/role=- | Beste beheerder, vanaf deze maand is ons rekeningnummer gewi |
| pay-05 | finance/high/reply=False/role=- | spam/low/reply=False/role=- | URGENT: your property account will be suspended. Verify your |
| lease-04 | legal/low/reply=True/role=- | legal/normal/reply=True/role=tenant | Hi, when exactly does my lease end, and is there a notice pe |
| contr-02 | maintenance/low/reply=False/role=- | maintenance/normal/reply=False/role=contractor | Monteur komt donderdag tussen 8 en 12 uur voor de lekkage op |
| contr-03 | maintenance/low/reply=False/role=- | maintenance/low/reply=False/role=contractor | The roof repair at Dorpsstraat 7 is finished. Invoice will f |
| admin-01 | administration/normal/reply=True/role=- | administration/low/reply=True/role=tenant | Ik ben mijn sleutel van de fietsenberging kwijt. Kan ik een  |
| admin-02 | administration/low/reply=True/role=- | administration/normal/reply=True/role=tenant | Hoe kan ik een parkeervergunning aanvragen voor de parkeerpl |
| other-01 | administration/normal/reply=True/role=- | administration/low/reply=False/role=- |  |
| other-02 | administration/low/reply=False/role=- | maintenance/low/reply=False/role=tenant | Bedankt voor de snelle hulp vorige week, alles werkt weer pr |
| role-legal-02 | new_projects/normal/reply=True/role=legal | legal/normal/reply=True/role=legal | Geachte heer Singh, de akte van levering voor Prinsengracht  |
| role-noise-auto-01 | administration/low/reply=False/role=- | business/low/reply=False/role=business | Uw aangifte is ontvangen. Dit is een automatisch bericht; u  |
| role-phish-lawyer-01 | finance/normal/reply=True/role=- | finance/normal/reply=False/role=- | Geachte heer Singh, ik ben advocaat Klaassen. Het rekeningnu |
