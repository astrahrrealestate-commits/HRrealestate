from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import Proposal

NOTE = {
    "type": "notify_owner",
    "case_id": str(uuid4()),
    "payload": {"kind": "notify_owner", "text": "Lekkage"},
    "rationale": "Owner should know",
    "context_ref": [],
    "draft_version": 1,
}


def test_one_to_four_actions() -> None:
    assert len(Proposal.model_validate({"actions": [NOTE]}).actions) == 1
    with pytest.raises(ValidationError):
        Proposal.model_validate({"actions": []})
    with pytest.raises(ValidationError):
        Proposal.model_validate({"actions": [NOTE] * 5})
