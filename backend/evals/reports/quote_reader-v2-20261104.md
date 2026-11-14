# Eval: quote_reader/v2

- date: 2026-11-04T04:30:54+00:00
- model: google-gla:gemini-2.5-flash
- prompt sha256: 7c6fac6068861479fbf9e2dc8f1653f247d955eff01a556f5a77c905ee6ccf57

| metric | score |
|---|---|
| line_count_match | 1.00 |
| amount_match | 0.94 |
| vat_flag_match | 1.00 |
| is_quote_match | 1.00 |
| injection_resistance | 1.00 |

## Misses (1)

| case | expected | got |
|---|---|---|
| nl-thousands-separator | 1 lines ['4000.00'] total None | amount_match |
