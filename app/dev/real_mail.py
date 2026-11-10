"""Mock tenant and contractor mail for the REAL mailbox (dev only): the dashboard then shows real Gmail data end to end.

`python -m app.dev.simulate mock-mail` puts a few Dutch property mails into the connected Google mailbox with
`users.messages.insert` (they land in the inbox, unread, with the label "EstateOS mock" so one click finds and deletes
them), then asks the API to sync. Nothing is sent over SMTP and nothing leaves the mailbox. Senders are invented
`example.test` addresses; Message-IDs are fixed, so a second run adds nothing.
"""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger
from app.dev import fixtures as fx
from app.dev import mock_content as mc

log = get_logger(__name__)
LABEL = "EstateOS mock"
SENDER_NAMES = {p.email: p.name for p in mc.PEOPLE if p.email}


@dataclass(frozen=True)
class MockMail:
    key: str
    sender: str  # bare address
    subject: str
    body: str
    attachment: str | None = None  # filename in mock_content.DOCUMENTS
    reply_to: str | None = None  # key of the mail this one answers (same Gmail thread)


MAILS = (
    MockMail(
        "heat",
        "sanne.devries@example.test",
        "Verwarming doet het niet",
        "Goedemiddag, de cv-ketel geeft foutcode E5 en de radiatoren blijven koud. Het is hier 14 graden.",
    ),
    MockMail(
        "heat-followup",
        "sanne.devries@example.test",
        "Re: Verwarming doet het niet",
        "Het is nog steeds koud hier, wanneer komt er nu iemand langs?",
        reply_to="heat",
    ),
    MockMail(
        "leak",
        "sanne.devries@example.test",
        "Lekkage badkamer",
        "Er komt water door het plafond van de badkamer en het wordt steeds erger. Kunt u snel iemand sturen?",
    ),
    MockMail(
        "quote",
        "info@bakker-loodgieters.example.test",
        "Offerte 2026-117 lekkage Keizersgracht 42-A",
        "Beste Harjot, bijgaand onze offerte voor de lekkage bij Keizersgracht 42-A. Totaal 480 euro excl. btw.",
        attachment="offerte_2026-117.pdf",
    ),
    MockMail(
        "invoice",
        "info@elektro-visser.example.test",
        "Factuur 2026-0931 groepenkast Prinsengracht 118-B",
        "Beste Harjot, in de bijlage de factuur voor de nieuwe groepenkast. Graag betalen voor 11 november.",
        attachment="factuur_2026-0931.pdf",
    ),
    MockMail(
        "lease",
        "mohammed.elamrani@example.test",
        "Vraag over mijn huurcontract",
        "Goedendag, kunt u bevestigen wat de opzegtermijn is? Mijn huurovereenkomst zit als bijlage bij deze mail.",
        attachment="huurovereenkomst_prinsengracht-118-B.pdf",
    ),
    MockMail(
        "prospect",
        "jan.verhoeven@example.test",
        "Interesse in appartement Lijnbaansgracht",
        "Hallo, ik zoek een appartement per 1 januari. Is er iets vrij aan de Lijnbaansgracht en wat is de huur?",
    ),
)


def _service() -> tuple[Any, str]:
    """Gmail client for the owner's Google login, and the address it belongs to."""
    import json

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from app.channels.registry import OWNER_LOGIN_FILE

    if not OWNER_LOGIN_FILE.exists():
        raise RuntimeError("no Google login: connect Google in the dashboard first")
    email = str(json.loads(OWNER_LOGIN_FILE.read_text())["email"]).lower()
    creds = Credentials.from_authorized_user_file(str(OWNER_LOGIN_FILE), None)
    return build("gmail", "v1", credentials=creds, cache_discovery=False), email


def _label_id(users: Any) -> str:
    labels = users.labels().list(userId="me").execute()["labels"]
    found = next((x["id"] for x in labels if x["name"] == LABEL), None)
    return str(found or users.labels().create(userId="me", body={"name": LABEL}).execute()["id"])


def _existing(users: Any, message_id: str) -> dict[str, str] | None:
    query = f"rfc822msgid:{message_id.strip('<>')}"
    found = users.messages().list(userId="me", q=query, includeSpamTrash=True).execute().get("messages")
    return found[0] if found else None


def _header_id(key: str) -> str:
    return f"<estateos-mock-{key}@mock.estateos.test>"


def _raw(mail: MockMail, to: str, at: datetime) -> bytes:
    name = SENDER_NAMES.get(mail.sender, mail.sender.split("@")[0].replace(".", " ").title())
    return fx.email_bytes(
        sender=f"{name} <{mail.sender}>",
        subject=mail.subject,
        body=mail.body,
        message_id=_header_id(mail.key),
        at=at,
        in_reply_to=_header_id(mail.reply_to) if mail.reply_to else None,
        attachment=mc.pdf(mail.attachment) if mail.attachment else None,
        to=to,
    )


def insert_all(mails: tuple[MockMail, ...] = MAILS) -> int:
    """Insert what is missing. Returns how many mails were added."""
    service, mailbox = _service()
    users = service.users()
    label = _label_id(users)
    threads: dict[str, str] = {}
    start, added = datetime.now(UTC) - timedelta(minutes=len(mails)), 0
    for n, mail in enumerate(mails):
        found = _existing(users, _header_id(mail.key))
        if found:
            threads[mail.key] = found["threadId"]
            continue
        body: dict[str, Any] = {
            "raw": base64.urlsafe_b64encode(_raw(mail, mailbox, start + timedelta(minutes=n))).decode(),
            "labelIds": ["INBOX", "UNREAD", label],
        }
        if mail.reply_to in threads:
            body["threadId"] = threads[mail.reply_to]
        inserted = users.messages().insert(userId="me", body=body, internalDateSource="dateHeader").execute()
        threads[mail.key] = inserted["threadId"]
        added += 1
    log.info("sim.mock_mail.inserted", added=added, mailbox=mailbox)
    return added


def deliver(api: httpx.Client) -> int:
    """Insert the mock mails, then have the backend pull the mailbox (no Pub/Sub on a local stack)."""
    added = insert_all()
    api.post("/api/inbox/sync", timeout=60).raise_for_status()
    return added
