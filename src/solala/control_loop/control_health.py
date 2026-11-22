from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum, auto


class Severity(IntEnum):
    """
    Operational health severity, ordered from LIVE to WARNING.
    """

    LIVE = auto()
    CAUTION = auto()
    WARNING = auto()


@dataclass(frozen=True)
class HealthIssue:
    """
    Snapshot of an active operational issue.

    Attributes:
        key: Stable identifier for the failing operation.
        severity: Consequence of the failure.
        message: User-readable description.
        first_seen: Time at which the issue was first reported.
        last_seen: Time of the most recent failure.
        occurrences: Number of failure reports since the last recovery.
    """

    key: str
    severity: Severity
    message: str
    first_seen: datetime
    last_seen: datetime
    occurrences: int


class ControlHealth:
    """
    Track operational issues independently of control decisions.

    This class does not detect loop stalls, browser disconnections, or decide
    whether a hardware command should be retried. Those responsibilities
    belong to the server and control loop.
    """

    def __init__(self) -> None:
        self._issues: dict[str, HealthIssue] = {}

    @property
    def severity(self) -> Severity:
        """
        Return the highest severity among active issues.
        """
        return max(
            (issue.severity for issue in self._issues.values()),
            default=Severity.LIVE
        )

    def get_issues(self) -> tuple[HealthIssue, ...]:
        """
        Return a severity-ordered immutable snapshot of active issues.
        """
        return tuple(
            sorted(
                self._issues.values(),
                key=lambda issue: (-issue.severity, issue.first_seen, issue.key)
            )
        )

    def report_failure(self, key: str, severity: Severity, message: str) -> bool:
        """
        Record a failure and return whether the visible issue changed.

        Args:
            key: Stable identity of the failing operation.
            severity: CAUTION or WARNING.
            message: User-readable failure description.

        Returns:
            True for a new issue or a changed severity/message; otherwise False.

        Raises:
            ValueError: If the key or message is blank, or severity is LIVE.
        """
        if not key.strip() or not message.strip() or severity not in (Severity.CAUTION, Severity.WARNING):
            raise ValueError('a failure requires a key, a message, and a severity of CAUTION or WARNING')

        now = datetime.now(timezone.utc)
        previous = self._issues.get(key)
        if previous is None:
            self._issues[key] = HealthIssue(key, severity, message, now, now, 1)
            return True

        changed = previous.severity != severity or previous.message != message
        self._issues[key] = replace(
            previous, severity=severity, message=message,
            last_seen=now, occurrences=previous.occurrences + 1
        )
        return changed

    def report_success(self, key: str) -> bool:
        """
        Clear an issue after its failed requirement is confirmed restored.

        Args:
            key: Stable identity of the recovered operation.

        Returns:
            True if an active issue was cleared.
        """
        return self._issues.pop(key, None) is not None
