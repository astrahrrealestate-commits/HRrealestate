"""The API enqueues due diligence runs by name with a deterministic workflow id on the documents queue."""

from typing import Any
from uuid import uuid4

from app.api.v1.enqueue import enqueue_dd_review
from app.core.workflow_names import DD_REVIEW, DOCUMENTS_QUEUE, dd_workflow_id


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> None:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> None:
        raise AssertionError("not used")


def test_review_run_has_a_deterministic_id_and_is_partitioned_by_company() -> None:
    client, company, review = RecordingClient(), uuid4(), uuid4()
    enqueue_dd_review(client, company, review, 3)
    [(options, args)] = client.calls
    assert options == {
        "queue_name": DOCUMENTS_QUEUE,
        "workflow_name": DD_REVIEW,
        "workflow_id": f"dd:{review}:3",
        "queue_partition_key": str(company),
    }
    assert args == (str(company), str(review), 3)


def test_each_run_number_is_its_own_workflow() -> None:
    review = uuid4()
    assert dd_workflow_id(review, 1) != dd_workflow_id(review, 2)
    assert dd_workflow_id(review, 1) == dd_workflow_id(review, 1)
