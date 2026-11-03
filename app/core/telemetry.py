"""Error reporting and tracing. Every exporter is a no-op when its credentials are absent."""

import sentry_sdk
from sentry_sdk.scrubber import EventScrubber

from app.core.redaction import sentry_denylist
from app.core.settings import Settings


def init_telemetry(settings: Settings) -> None:
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            release=settings.app_version,
            send_default_pii=False,
            traces_sample_rate=0.0,
            include_local_variables=False,  # frame locals can hold BRIXX rows or message bodies
            event_scrubber=EventScrubber(denylist=sentry_denylist(), recursive=True),
        )
