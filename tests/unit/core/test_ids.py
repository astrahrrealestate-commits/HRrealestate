import uuid

from app.core.ids import new_id


def test_new_id_is_uuid7_and_time_ordered() -> None:
    ids = [new_id() for _ in range(50)]
    assert all(isinstance(i, uuid.UUID) and i.version == 7 for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == 50
