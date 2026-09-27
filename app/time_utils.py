from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC now — datetime.utcnow() is deprecated as of Python 3.12."""
    return datetime.now(timezone.utc)
