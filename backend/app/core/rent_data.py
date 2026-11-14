"""Whether rent and payment data is mirrored into EstateOS at all.

Rent amounts, payments and arrears arrive with the BRIXX rent mirror. Until then every rent figure is *unknown*, not
zero, and nothing may answer "who is overdue" or "what was paid" from the database.
"""

RENT_DATA_AVAILABLE = False
