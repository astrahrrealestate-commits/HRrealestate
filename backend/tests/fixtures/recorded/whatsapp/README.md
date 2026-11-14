# WhatsApp Cloud API webhook fixtures

Source: Meta WhatsApp Cloud API webhook payload shapes as documented (messages, statuses, interactive replies,
Coexistence `smb_message_echoes`). Built by hand, not captured; all identifiers fictional:
phone_number_id `100000000000001`, business display `4915550000999`, tenant `4915550000001`, owner `4915550000100`,
`wamid.TEST####` / `wamid.OUT####` / `wamid.ECHO####`, media `MEDIA####`, timestamp 1759737600.

**Verify on go-live:** capture one real payload per type with `make live-check` tooling and diff against these
(especially `smb_message_echoes`, whose shape is the least documented). Add captures as new files; never edit these.
