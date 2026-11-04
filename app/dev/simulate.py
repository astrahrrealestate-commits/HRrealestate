"""Channel simulator: drives the running API exactly like the providers would (signed webhooks, Pub/Sub pushes).

    python -m app.dev.simulate seed
    python -m app.dev.simulate wa --from +4915550000001 --text "Heizung kalt" [--image foto.jpg]
    python -m app.dev.simulate wa-button --id apr:<uuid>:ok --title Freigeben --reply-to wamid.X
    python -m app.dev.simulate gmail --from "Mieter <m@example.test>" --subject Heizung --body "..." [--attach f.pdf]
    python -m app.dev.simulate demo

WhatsApp: a Cloud API webhook signed with the dev app secret; images go to the shared fake media directory first.
Gmail: the mail is appended to the shared fake mailbox, then a Pub/Sub push signed with the dev OIDC key is posted.
Fake providers only: refuses to run in prod or against real providers.
"""

import argparse
import mimetypes
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import Engine

from app.channels import registry
from app.channels.gmail.push import DEV_AUDIENCE, DEV_SERVICE_ACCOUNT
from app.channels.whatsapp.media import MediaBlob
from app.channels.whatsapp.webhook_auth import DEV_APP_SECRET, sign_body
from app.core.errors import UnsafeConfigurationError
from app.core.logging import configure_logging, get_logger
from app.core.settings import Settings, get_settings
from app.dev import fixtures as fx
from app.dev.keys import ensure_dev_keys, sign_push_token

log = get_logger(__name__)


def ensure_simulation_allowed(settings: Settings) -> None:
    """Never in prod; WhatsApp is always simulated (owner taps). Gmail may be real (`gmail-pull` testing), then no
    fake mail can be injected."""
    if settings.env == "prod" or settings.whatsapp_provider != "fake":
        raise UnsafeConfigurationError("the simulator only runs outside prod with a fake WhatsApp provider")


class Simulator:
    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        ensure_simulation_allowed(settings)
        self._settings = settings
        self._http = http

    @property
    def api(self) -> httpx.Client:
        """The API client (cookies persist), for scenarios that call the v1 routes."""
        return self._http

    def whatsapp(
        self,
        sender_e164: str,
        text: str,
        *,
        name: str = "Mieter",
        image: fx.Attachment | None = None,
        document: fx.Attachment | None = None,
    ) -> str:
        wamid, now = f"wamid.SIM{uuid4().hex.upper()}", datetime.now(UTC)
        file = image or document
        if file is None:
            message = fx.wa_text(wamid, text, now)
        else:
            media_id, blob = f"SIM{uuid4().hex}", MediaBlob(file.data, file.mime_type)
            registry.fake_whatsapp_media(self._settings).put(media_id, blob)
            if document is not None:
                message = fx.wa_document(wamid, media_id, blob.sha256, file.mime_type, file.filename, text or None, now)
            else:
                message = fx.wa_image(wamid, media_id, blob.sha256, text or None, now)
        self._post_whatsapp(fx.wa_webhook(pnid=fx.DEV_PNID, sender_e164=sender_e164, name=name, message=message))
        return wamid

    def button(self, button_id: str, title: str, reply_to: str, *, sender_e164: str = fx.DEV_OWNER_E164) -> str:
        wamid = f"wamid.SIM{uuid4().hex.upper()}"
        message = fx.wa_button(wamid, button_id, title, datetime.now(UTC), reply_to)
        self._post_whatsapp(fx.wa_webhook(pnid=fx.DEV_PNID, sender_e164=sender_e164, name="Owner", message=message))
        return wamid

    def gmail(
        self,
        sender: str,
        subject: str,
        body: str,
        *,
        in_reply_to: str | None = None,
        attachment: fx.Attachment | None = None,
    ) -> str:
        if self._settings.gmail_provider != "fake":
            raise UnsafeConfigurationError(
                "simulated mail needs GMAIL_PROVIDER=fake (use gmail-pull for a real mailbox)"
            )
        """Deliver a mail to the dev mailbox and push the notification. Returns its RFC 822 Message-ID."""
        mailbox = registry.fake_gmail_mailbox(self._settings, fx.DEV_MAILBOX)
        message_id = f"<{uuid4().hex}@sim.estateos.test>"
        raw = fx.email_bytes(
            sender=sender,
            subject=subject,
            body=body,
            message_id=message_id,
            at=datetime.now(UTC),
            in_reply_to=in_reply_to,
            attachment=attachment,
        )
        parent = mailbox.find_by_header("Message-ID", in_reply_to, "INBOX") if in_reply_to else None
        thread = mailbox.get_message(parent).thread_id if parent else None
        mailbox.add_message(raw, labels=["INBOX", "UNREAD"], thread_id=thread)
        self._push(mailbox.current_history_id())
        return message_id

    def _post_whatsapp(self, body: bytes) -> None:
        headers = {"x-hub-signature-256": sign_body(DEV_APP_SECRET, body), "content-type": "application/json"}
        self._http.post("/webhooks/whatsapp", content=body, headers=headers).raise_for_status()

    def _push(self, history_id: int) -> None:
        private_pem, _ = ensure_dev_keys(self._settings.dev_signing_dir)
        token = sign_push_token(
            private_pem,
            audience=self._settings.gmail_pubsub_audience or DEV_AUDIENCE,
            email=self._settings.gmail_pubsub_service_account or DEV_SERVICE_ACCOUNT,
        )
        body = fx.pubsub_envelope(fx.DEV_MAILBOX, history_id, f"sim-{uuid4().hex}")
        headers = {"authorization": f"Bearer {token}", "content-type": "application/json"}
        self._http.post("/webhooks/gmail/push", content=body, headers=headers).raise_for_status()


def _attachment(path: str | None) -> fx.Attachment | None:
    if path is None:
        return None
    file = Path(path)
    mime_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return fx.Attachment(file.name, mime_type, file.read_bytes())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.dev.simulate", description="Drive the API like WhatsApp and Gmail do.")
    parser.add_argument("--api", help="API base URL (default: http://127.0.0.1:<API_PORT>)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="create the dev company, channel accounts and owner (idempotent)")
    wa = sub.add_parser("wa", help="inbound WhatsApp text or image")
    wa.add_argument("--from", dest="sender", required=True, help="E.164, e.g. +4915550000001")
    wa.add_argument("--text", default="")
    wa.add_argument("--name", default="Mieter")
    wa.add_argument("--image", help="path to a JPEG/PNG to send as image (text becomes the caption)")
    button = sub.add_parser("wa-button", help="owner taps an interactive button")
    button.add_argument("--id", required=True, help="button id, e.g. apr:<action uuid>:ok")
    button.add_argument("--title", default="Freigeben")
    button.add_argument("--reply-to", required=True, help="wamid of the message carrying the button")
    button.add_argument("--from", dest="sender", default=fx.DEV_OWNER_E164)
    gmail = sub.add_parser("gmail", help="inbound mail to the dev mailbox + Pub/Sub push")
    gmail.add_argument("--from", dest="sender", required=True)
    gmail.add_argument("--subject", required=True)
    gmail.add_argument("--body", required=True)
    gmail.add_argument("--in-reply-to", help="Message-ID of an earlier mail (same thread)")
    gmail.add_argument("--attach", help="path to a file to attach")
    pull = sub.add_parser("gmail-pull", help="real mailbox: register it and sync it once now (no Pub/Sub needed)")
    pull.add_argument("--mailbox", required=True)
    pull.add_argument(
        "--backfill", action="store_true", help="first pull reads the last day of mail (default: only new)"
    )
    sub.add_parser("pending", help="pending approvals for the dev company, with the tap to approve each")
    approve = sub.add_parser("approve", help="tap a pending approval as Harjot (simulated WhatsApp)")
    approve.add_argument("--n", type=int, default=1, help="row number from `pending` (1 = newest)")
    approve.add_argument("--choice", default="d1", choices=["ok", "d1", "d2", "d3", "rej"])
    tour = sub.add_parser("tour", help="mock portfolio + one scripted day so every agent runs (needs the live stack)")
    tour.add_argument("--timeout", type=float, default=120.0)
    demo = sub.add_parser("demo", help="seed, run the parity and dashboard scenarios and assert the stored rows (G5)")
    demo.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.env)
    ensure_simulation_allowed(settings)
    from app.db.session import make_engine  # deferred: `--help` works without a database

    engine = make_engine(settings.sqlalchemy_url)
    try:
        with httpx.Client(base_url=args.api or f"http://127.0.0.1:{settings.api_port}", timeout=10) as http:
            return _run(args, Simulator(settings, http), engine, settings)
    finally:
        engine.dispose()


def _run(args: argparse.Namespace, sim: Simulator, engine: Engine, settings: Settings) -> int:
    from app.dev.demo import run_demo
    from app.dev.seed import seed_dev_tenant

    if args.command == "demo":
        return run_demo(sim, engine, settings, timeout=args.timeout)
    if args.command == "tour":
        from app.dev.mock_tour import run_tour

        return run_tour(sim, engine, settings, timeout=args.timeout)
    if args.command in ("gmail-pull", "pending", "approve"):
        return _run_real_gmail(args, sim, engine, settings)
    if args.command == "seed":
        log.info("sim.seeded", company_id=str(seed_dev_tenant(engine).company_id))
    elif args.command == "wa":
        image = _attachment(args.image)
        log.info("sim.whatsapp", wamid=sim.whatsapp(args.sender, args.text, name=args.name, image=image))
    elif args.command == "wa-button":
        log.info("sim.button", wamid=sim.button(args.id, args.title, args.reply_to, sender_e164=args.sender))
    else:
        attachment = _attachment(args.attach)
        mid = sim.gmail(args.sender, args.subject, args.body, in_reply_to=args.in_reply_to, attachment=attachment)
        log.info("sim.gmail", message_id=mid)
    return 0


def _run_real_gmail(args: argparse.Namespace, sim: Simulator, engine: Engine, settings: Settings) -> int:
    from dbos import DBOSClient

    from app.contracts import ButtonChoice, ButtonId
    from app.dev import real_gmail
    from app.dev.seed import seed_dev_tenant

    if args.command == "gmail-pull":
        client = DBOSClient(system_database_url=settings.dbos_database_url)
        try:
            log.info(
                "sim.gmail_pull",
                workflow_id=real_gmail.pull_mailbox(engine, settings, client, args.mailbox, backfill=args.backfill),
            )
        finally:
            client.destroy()
        return 0
    pending = real_gmail.pending_approvals(engine, seed_dev_tenant(engine).company_id)
    if args.command == "pending":
        for p in pending:
            sys.stdout.write(f"{p.n}. [{p.kind}] {p.case_label}: {p.draft_preview}\n")
        sys.stdout.write("approve with: python -m app.dev.simulate approve --n <n> --choice d1|d2|d3|ok|rej\n")
        return 0
    chosen = next((p for p in pending if p.n == args.n), None)
    if chosen is None:
        sys.stderr.write(f"no pending approval #{args.n}\n")
        return 1
    button = ButtonId(approval_id=chosen.approval_id, choice=ButtonChoice(args.choice)).render()
    log.info("sim.approve", wamid=sim.button(button, "Approve", chosen.card_wamid or "wamid.SIMCARD"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
