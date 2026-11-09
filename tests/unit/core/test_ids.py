import uuid

from app.core.ids import new_id


def test_new_id_is_uuid7_and_time_ordered() -> None:
    ids = [new_id() for _ in range(50)]
    assert all(isinstance(i, uuid.UUID) and i.version == 7 for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == 50


def test_case_ref_differs_for_cases_created_together() -> None:
    from app.core.ids import case_ref

    refs = {case_ref(new_id()) for _ in range(50)}
    assert len(refs) == 50


def test_case_ref_is_the_random_tail_not_the_timestamp_head() -> None:
    from app.core.ids import case_ref

    case_id = new_id()
    assert case_ref(case_id) == case_id.hex[-6:]
    assert case_ref(case_id) not in case_id.hex[:8]
