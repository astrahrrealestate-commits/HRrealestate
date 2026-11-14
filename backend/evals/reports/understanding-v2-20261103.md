# Eval: understanding/v2

- date: 2026-11-03T18:49:41+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: 1b01ab765f1c2d26811263822045c99750c9d275f53f13e4af84b11dcf82f763

| metric | score |
|---|---|
| category_accuracy | 0.88 |
| urgency_accuracy | 0.71 |
| emergency_recall | 1.00 |
| suspicious_recall | 1.00 |
| reply_flag_accuracy | 0.97 |
| needless_draft_rate | 0.00 |
| missed_reply_rate | 0.04 |

## Misses (12)

| case | expected | got | text |
|---|---|---|---|
| maint-06 | maintenance/low/reply=True | maintenance/normal/reply=True | De deurbel doet het niet meer. Geen haast, maar wel handig a |
| maint-08 | maintenance/high/reply=True | maintenance/emergency/reply=True | Het slot van de voordeur is kapot, de deur gaat niet meer op |
| pay-02 | payment/low/reply=True | payment/normal/reply=True | Kunt u mij een overzicht sturen van de betaalde huur over 20 |
| pay-05 | payment/high/reply=False | spam/low/reply=False | URGENT: your property account will be suspended. Verify your |
| lease-04 | lease/low/reply=True | lease/normal/reply=True | Hi, when exactly does my lease end, and is there a notice pe |
| compl-01 | complaint/normal/reply=True | complaint/high/reply=True | De buren boven hebben elke nacht tot 3 uur harde muziek. Ik  |
| compl-02 | complaint/normal/reply=True | maintenance/high/reply=True | Al vier weken wacht ik op een reactie over de lekkende kraan |
| admin-02 | admin/low/reply=True | admin/normal/reply=True | Hoe kan ik een parkeervergunning aanvragen voor de parkeerpl |
| admin-03 | admin/low/reply=True | admin/normal/reply=True | Mijn nieuwe telefoonnummer is 06-12345678. Wilt u dit aanpas |
| other-01 | other/normal/reply=True | other/low/reply=False |  |
| fyi-01 | other/low/reply=False | spam/low/reply=False | INR 65.00 was debited from your A/c no. XX8614 on 07-10-2026 |
| fyi-03 | other/low/reply=False | admin/low/reply=False | Automatisch antwoord: ik ben tot en met 20 oktober afwezig e |
