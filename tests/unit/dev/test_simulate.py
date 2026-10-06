import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.channels.gmail.push import DEV_AUDIENCE, DEV_SERVICE_ACCOUNT, local_push_verifier
from app.channels.whatsapp.inbound import WaInbound, parse_webhook
from app.channels.whatsapp.webhook_auth import DEV_APP_SECRET, verify_signature
from app.contracts import Direction
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.dev import demo
from app.dev import fixtures as fx
from app.dev.simulate import Simulator


def _settings(tmp_path: Path, **kw: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@h/db",
        storage_local_dir=tmp_path / "data",
        dev_signing_dir=tmp_path / "keys",
        _env_file=None,
        **kw,
    )


@pytest.mark.parametrize(
    "override", [{"whatsapp_provider": "360dialog"}, {"gmail_provider": "google"}, {"env": "prod"}]
)
def test_refuses_prod_and_real_providers(tmp_path: Path, override: dict[str, str]) -> None:
    with pytest.raises(UnsafeConfigurationError, match="fake providers"):
        Simulator(_settings(tmp_path, **override), httpx.Client())


def test_cli_refuses_prod_before_touching_the_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.db.session
    import app.dev.simulate

    def no_engine(*_a: object) -> None:
        raise AssertionError("engine created")

    monkeypatch.setattr(app.dev.simulate, "get_settings", lambda: _settings(tmp_path, env="prod"))
    monkeypatch.setattr(app.db.session, "make_engine", no_engine)
    with pytest.raises(UnsafeConfigurationError):
        app.dev.simulate.main(["seed"])


class Capture:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200 if request.url.path.endswith("whatsapp") else 204)


def _sim(tmp_path: Path) -> tuple[Simulator, Capture, Settings]:
    capture, settings = Capture(), _settings(tmp_path)
    http = httpx.Client(transport=httpx.MockTransport(capture), base_url="http://api")
    return Simulator(settings, http), capture, settings


def test_whatsapp_image_is_signed_and_its_media_is_downloadable(tmp_path: Path) -> None:
    from app.channels import registry

    sim, capture, settings = _sim(tmp_path)
    wamid = sim.whatsapp("+4915550000001", "Foto", image=demo.PHOTO)
    [request] = capture.requests
    verify_signature(request.content, request.headers["x-hub-signature-256"], DEV_APP_SECRET)  # raises if wrong
    [event] = parse_webhook(request.content)
    assert isinstance(event, WaInbound)
    assert event.media is not None
    assert (event.wamid, event.media.sha256) == (wamid, hashlib.sha256(demo.PHOTO.data).hexdigest())
    assert registry.whatsapp_media(settings, fx.DEV_PNID).download(event.media.id).data == demo.PHOTO.data


def test_gmail_reply_lands_in_the_same_thread_and_push_verifies(tmp_path: Path) -> None:
    from app.channels import registry

    sim, capture, settings = _sim(tmp_path)
    first = sim.gmail("m@example.test", "Heizung", "kalt")
    sim.gmail("m@example.test", "Re: Heizung", "Foto", in_reply_to=first, attachment=demo.PHOTO)
    verifier = local_push_verifier(settings.dev_signing_dir, DEV_AUDIENCE, DEV_SERVICE_ACCOUNT)
    notices = [verifier.verify(r.headers["authorization"], r.content) for r in capture.requests]
    assert [n.history_id for n in notices] == [1, 2]
    mailbox = registry.fake_gmail_mailbox(settings, fx.DEV_MAILBOX)
    threads = {mailbox.get_message(mid).thread_id for mid in mailbox.history_since(0).message_ids}
    assert len(threads) == 1


def _row(text: str, sender: str = demo.TENANT_E164, thread: str | None = "t", photos: tuple[str, ...] = ()) -> demo.Row:
    return demo.Row(uuid4(), Direction.inbound, sender, text, thread, photos)


def test_parity_check_reports_each_kind_of_mismatch() -> None:
    sha = hashlib.sha256(demo.PHOTO.data).hexdigest()
    wa = [_row(demo.TEXTS[0]), _row(demo.TEXTS[1], photos=(sha,))]
    gm = [_row(demo.TEXTS[0], demo.TENANT_EMAIL, "a"), _row(demo.TEXTS[1], demo.TENANT_EMAIL, "b")]  # split, no photo
    button = [_row("Freigeben", fx.DEV_OWNER_E164)]
    routes = {r.id: "pipe" for r in (*wa, *gm, *button)}  # button routed to the pipeline instead of the owner
    found = demo.problems((wa, gm, button), routes)
    assert [p.split(":")[0] for p in found] == ["gmail", "gmail", "owner button"]
    no_thread = [_row(demo.TEXTS[0], thread=None), _row(demo.TEXTS[1], thread=None, photos=(sha,))]
    assert any("threads" in p for p in demo.problems((no_thread, [], []), routes | {r.id: "pipe" for r in no_thread}))
    ok_gm = [_row(demo.TEXTS[0], demo.TENANT_EMAIL), _row(demo.TEXTS[1], demo.TENANT_EMAIL, photos=(sha,))]
    assert demo.problems((wa, ok_gm, button), {**routes, button[0].id: "owner"} | {r.id: "pipe" for r in ok_gm}) == []
