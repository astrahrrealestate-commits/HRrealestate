from app.core.errors import (
    EstateOSError,
    IllegalTransitionError,
    InvalidButtonIdError,
    NotFoundError,
    PromptNotFoundError,
    TenantMismatchError,
)


def test_hierarchy() -> None:
    for exc in (IllegalTransitionError, InvalidButtonIdError, NotFoundError, PromptNotFoundError, TenantMismatchError):
        assert issubclass(exc, EstateOSError)
    assert issubclass(InvalidButtonIdError, ValueError)  # usable inside pydantic validators
