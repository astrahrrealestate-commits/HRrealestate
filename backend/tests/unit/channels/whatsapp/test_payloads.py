import pytest

from app.channels.whatsapp.payloads import Button, ListRow, ListSection, buttons, list_menu, template, text

TO = "+4915550000100"


def test_text_payload() -> None:
    assert text(TO, "Hallo", reply_to="wamid.X") == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "4915550000100",
        "type": "text",
        "text": {"body": "Hallo", "preview_url": False},
        "context": {"message_id": "wamid.X"},
    }


def test_buttons_payload() -> None:
    p = buttons(TO, "Entwurf freigeben?", [Button("apr:1:ok", "Freigeben"), Button("apr:1:rej", "Ablehnen")])
    assert p["type"] == "interactive"
    assert p["interactive"]["type"] == "button"
    assert p["interactive"]["body"] == {"text": "Entwurf freigeben?"}
    assert p["interactive"]["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "apr:1:ok", "title": "Freigeben"}},
        {"type": "reply", "reply": {"id": "apr:1:rej", "title": "Ablehnen"}},
    ]


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [Button(f"id{i}", "t") for i in range(4)],
        [Button("id", "x" * 21)],
        [Button("", "t")],
        [Button("x" * 257, "t")],
        [Button("same", "a"), Button("same", "b")],
    ],
)
def test_button_limits(bad: list[Button]) -> None:
    with pytest.raises(ValueError):
        buttons(TO, "body", bad)


def test_body_limits() -> None:
    assert text(TO, "x" * 4096)["text"]["body"] == "x" * 4096
    for bad in (
        lambda: text(TO, "x" * 4097),
        lambda: text(TO, ""),
        lambda: buttons(TO, "x" * 1025, [Button("a", "b")]),
    ):
        with pytest.raises(ValueError):
            bad()


def test_list_payload_and_limits() -> None:
    sec = ListSection("Entwürfe", [ListRow("apr:1:d1", "Entwurf 1", "förmlich"), ListRow("apr:1:d2", "Entwurf 2")])
    p = list_menu(TO, "Welcher Entwurf?", "Auswählen", [sec])
    assert p["interactive"]["type"] == "list"
    assert p["interactive"]["action"]["button"] == "Auswählen"
    assert p["interactive"]["action"]["sections"][0]["rows"][1] == {"id": "apr:1:d2", "title": "Entwurf 2"}
    too_many = ListSection("s", [ListRow(f"r{i}", "t") for i in range(11)])
    with pytest.raises(ValueError):
        list_menu(TO, "b", "Auswählen", [too_many])
    with pytest.raises(ValueError):
        list_menu(TO, "b", "x" * 21, [sec])
    with pytest.raises(ValueError):
        list_menu(TO, "b", "ok", [ListSection("s", [ListRow("r", "x" * 25)])])


def test_template_without_params_has_no_components() -> None:
    assert "components" not in template(TO, "daily_briefing", "de", [])["template"]


@pytest.mark.parametrize("param", ["a\nb", "a\tb", "a     b", ""])
def test_template_rejects_params_meta_refuses(param: str) -> None:
    with pytest.raises(ValueError):
        template(TO, "daily_briefing", "de", [param])


def test_list_section_needs_rows() -> None:
    with pytest.raises(ValueError):
        list_menu(TO, "b", "ok", [ListSection("empty", []), ListSection("s", [ListRow("r", "t")])])


def test_template_payload() -> None:
    p = template(TO, "daily_briefing", "de", ["3", "1"])
    assert p["template"] == {
        "name": "daily_briefing",
        "language": {"code": "de"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": "3"}, {"type": "text", "text": "1"}]}],
    }


def test_recipient_must_be_e164() -> None:
    with pytest.raises(ValueError):
        text("0151 2345", "x")
