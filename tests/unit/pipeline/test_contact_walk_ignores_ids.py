from app.core.ids import new_id
from app.pipeline.concierge_sanitize import has_contact_details
from tests.integration.concierge_support import readable_strings


def test_walk_helper_never_flags_generated_ids() -> None:
    flagged = 0
    for _ in range(2000):
        uid = str(new_id())
        results = [{"task_id": uid, "ref": uid[:8], "data": {"case_id": uid, "approval_ids": [uid]}, "x": uid}]
        flagged += any(has_contact_details(t) for t in readable_strings(results))
    assert flagged == 0


def test_walk_helper_keeps_free_text() -> None:
    walked = list(readable_strings([{"summary": "mail evil@attacker.test", "data": {"task_id": str(new_id())}}]))
    assert walked == ["mail evil@attacker.test"]
    assert any(has_contact_details(t) for t in walked)
