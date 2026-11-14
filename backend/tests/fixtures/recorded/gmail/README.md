# Gmail API v1 fixtures (`users.messages.get` with `format=raw`)

Built with Python's `email.message.EmailMessage`, serialised with CRLF (`policy.SMTP`, like real Gmail raw messages)
and base64url-encoded into the documented raw-message JSON (`id`, `threadId`, `labelIds`, `historyId`,
`internalDate`, `sizeEstimate`, `raw`). All addresses fictional (`*.example.test`); internalDate 1759737600000.

Cases: plain, html_only, multipart_alt_mixed (+PDF), latin1_qp, german_quote, outlook_quote, inline_image (cid),
attachment_only, sent_by_owner (SENT), missing_from, gmail_forward, german_forward, rfc822_attachment (.eml with its
own attachment), apple_split (text/image/text), calendar_invite, apple_inline_photo (disposition inline, no cid),
draft (DRAFT label), spam, forged_from_self (From = mailbox, no SENT), non_reply_with_von ("Von:" lines, not a reply).
**Verify on go-live:** capture real messages (Outlook, iOS Mail, Gmail web) and add them as new fixtures.
