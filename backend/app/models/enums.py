from enum import StrEnum


class ScanSession(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"


class ScanType(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class ScanStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # published, but at least one category had fewer than the target number of picks
    FAILED = "failed"

    @property
    def is_published(self) -> bool:
        return self in (ScanStatus.COMPLETED, ScanStatus.PARTIAL)


class CapCategory(StrEnum):
    SMALL = "small-cap"
    MID = "mid-cap"
    LARGE = "large-cap"


PUBLISHED_STATUSES = (ScanStatus.COMPLETED.value, ScanStatus.PARTIAL.value)
