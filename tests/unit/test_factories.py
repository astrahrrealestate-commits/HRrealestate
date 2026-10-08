from tests.factories import (
    ApprovalFactory,
    CaseFactory,
    ChannelAccountFactory,
    CompanyFactory,
    MessageRowFactory,
    OwnerAccountFactory,
    PersonFactory,
    RawEventFactory,
    TaskRowFactory,
    WaitRowFactory,
)


def test_factories_build() -> None:
    company = CompanyFactory.build()
    assert company.id is not None
    assert company.name

    person = PersonFactory.build()
    assert person.id is not None

    channel_account = ChannelAccountFactory.build()
    assert channel_account.id is not None

    owner_account = OwnerAccountFactory.build()
    assert owner_account.id is not None

    raw_event = RawEventFactory.build()
    assert raw_event.id is not None

    message = MessageRowFactory.build()
    assert message.id is not None

    case = CaseFactory.build()
    assert case.id is not None

    task = TaskRowFactory.build()
    assert task.id is not None

    wait = WaitRowFactory.build()
    assert wait.id is not None

    approval = ApprovalFactory.build()
    assert approval.id is not None
