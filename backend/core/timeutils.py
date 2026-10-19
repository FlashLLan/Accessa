from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware current time in UTC. Use instead of datetime.utcnow()."""
    return datetime.now(timezone.utc)
