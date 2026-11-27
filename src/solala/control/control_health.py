"""
Collect reported operational outcomes and expose read-only health snapshots.

Reporting clients call `report_failure()` and `report_success()`. In Solala,
the control loop reports outcomes from control steps, policies, commands, and
controller status reads. It also forwards completed consumer reads and
database measurement outcomes.

Reading clients call `snapshot()` to get the overall severity and immutable
active issues. The server's master alarm reads that data through
`get_control_health()` and combines it with the control-loop heartbeat.
An optional logging callback receives diagnostic messages for new or changed
issues and for recovery. The health tracker depends only on its inputs and
the supplied callback.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum, auto
from logging import ERROR, INFO


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
    Track operational issues and report meaningful changes.

    Reporting clients decide when an operation has failed or recovered and
    supply a stable issue key, severity, and user-facing message. Reading
    clients get snapshots that remain valid after subsequent updates.
    Use an instance on one event loop. Updates and snapshots are synchronous.
    """

    def __init__(self, *, log_event: Callable[[int, str, bool], None] | None = None) -> None:
        """
        Create an issue tracker with an optional synchronous log sink.

        Args:
            log_event: Optional output callback receiving log level, diagnostic
                message, and whether to include the active exception traceback.
                Called synchronously after an issue changes. A callback failure
                leaves the health update in place.
        """
        self._issues: dict[str, HealthIssue] = {}
        self._log_event = log_event

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

    def snapshot(self) -> tuple[Severity, tuple[HealthIssue, ...]]:
        """
        Return overall severity and immutable active issue details.

        The result reflects reports already received. Reading it leaves the
        issue tracker unchanged.
        """
        return self.severity, self.get_issues()

    def report_failure(
            self,
            key: str,
            severity: Severity,
            message: str,
            *,
            log_message: str | None = None,
            traceback: bool = False,
    ) -> bool:
        """
        Record a failed attempt and increment the issue's occurrence count.

        A diagnostic message is emitted for a new issue or a change in its
        severity or user-facing message.

        Args:
            key: Stable identity of the failing operation.
            severity: CAUTION or WARNING.
            message: User-readable failure description.
            log_message: Optional diagnostic message for a new or changed issue.
            traceback: Whether to include the active exception traceback in the log.

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
            changed = True
        else:
            changed = previous.severity != severity or previous.message != message
            self._issues[key] = replace(
                previous, severity=severity, message=message,
                last_seen=now, occurrences=previous.occurrences + 1
            )
        if changed and log_message is not None:
            self._emit_log(ERROR, log_message, traceback)
        return changed

    def report_success(self, key: str, *, log_message: str | None = None) -> bool:
        """
        Clear the active issue for this key. Log recovery if requested.

        Args:
            key: Stable identity of the recovered operation.
            log_message: Optional message to log if an issue was cleared.

        Returns:
            True if an active issue was cleared.
        """
        cleared = self._issues.pop(key, None) is not None
        if cleared and log_message is not None:
            self._emit_log(INFO, log_message, False)
        return cleared

    def _emit_log(self, level: int, message: str, traceback: bool) -> None:
        if self._log_event is not None:
            try:
                self._log_event(level, message, traceback)
            except Exception:
                # Keep health snapshots available even if logging fails.
                pass
