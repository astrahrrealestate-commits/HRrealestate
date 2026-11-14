"""Polyfactory factories for domain models in test fixtures."""

from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory

from app.db.models import (
    Approval,
    Case,
    ChannelAccount,
    Company,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    TaskRow,
    WaitRow,
)


class CompanyFactory(SQLAlchemyFactory[Company]):
    __model__ = Company


class PersonFactory(SQLAlchemyFactory[Person]):
    __model__ = Person


class ChannelAccountFactory(SQLAlchemyFactory[ChannelAccount]):
    __model__ = ChannelAccount


class OwnerAccountFactory(SQLAlchemyFactory[OwnerAccount]):
    __model__ = OwnerAccount


class RawEventFactory(SQLAlchemyFactory[RawEvent]):
    __model__ = RawEvent


class MessageRowFactory(SQLAlchemyFactory[MessageRow]):
    __model__ = MessageRow


class CaseFactory(SQLAlchemyFactory[Case]):
    __model__ = Case


class TaskRowFactory(SQLAlchemyFactory[TaskRow]):
    __model__ = TaskRow


class WaitRowFactory(SQLAlchemyFactory[WaitRow]):
    __model__ = WaitRow


class ApprovalFactory(SQLAlchemyFactory[Approval]):
    __model__ = Approval
