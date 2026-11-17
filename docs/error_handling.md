Error Handling and Recovery Policy
==================================

Status
------

This document defines the **intended** error-handling and recovery policy for
Solala. It is a design contract, not a claim that every behaviour described
here is already implemented. Implementation will be introduced and tested
incrementally.

Purpose and principles
----------------------

Solala controls real electrical equipment. A failure must not silently turn
an uncertain system state into an apparently successful control operation.

1. **Isolate failure.** A failed operation must not unnecessarily prevent
   independent operations from continuing.
2. **Protect against inconsistency.** Do not confuse requested, attempted,
   confirmed and unknown device states.
3. **Do no harm.** When essential inputs or control outcomes cannot be
   trusted, avoid actions that could make the situation less safe.
4. **Make best efforts.** Continue useful work and retry recoverable
   operations when it is safe to do so.
5. **Reassure the user.** Make normal operation immediately apparent, while
   clearly identifying degraded or unsafe conditions.
6. **Provide details on demand.** Keep the primary interface quiet and
   concise, with diagnostic detail accessible when requested.

Failure handling
----------------

The control loop should survive recoverable failures and unexpected exceptions
within an iteration. A failed subsystem must not stop unrelated work: for
example, a failed battery command should not prevent an independent inverter
command from being attempted when that command is safe.

Errors in individual consumers, forecasts, price services, measurement
persistence, register logging and UI listeners should be isolated at suitable
boundaries. The database loop must also remain operational after recoverable
database failures. A failure in one reporting source must not be represented
as a valid zero measurement or as a successful operation.

Normal shutdown and asyncio task cancellation are not operational failures.
Cancellation must propagate, and background tasks and connections must be
cleaned up reliably. Unexpected exceptions should be logged with enough
context to diagnose them, whether the control loop continues or not.

Control consistency and safety
------------------------------

Solala must distinguish the **requested mode**, the **command attempted**,
the **outcome of that attempt**, and the **last confirmed hardware state**.
These are not interchangeable. A command that raises an exception, times out
or completes only partially must not be recorded as confirmed successful.

Multi-register and multi-device operations can leave hardware in an
intermediate state. Their failure handling must preserve uncertainty and
reconcile actual state before retrying whenever necessary. Retrying a
command must be safe under the delegate's contract; blindly repeating a
partially completed sequence is not always sufficient.

Control decisions must not use invalid, expired or fabricated inputs as
though they were current measurements. Cached data may support reporting
when clearly marked as stale, but its use for control must satisfy the
specific safety requirements of the policy. In particular, zero-export
control requires trustworthy measurements and confirmation of the relevant
inverter commands. A communication failure or register reversion timer is
not proof that zero-export remains enforced.

When a requested action cannot be completed safely, Solala should retain
the user's intent where appropriate, report the failure, and continue other
safe operations. It must not claim that the physical system has reached the
requested state.

Recovery and logging
--------------------

Transient failures should be retried automatically when safe, with retry
frequency appropriate to the operation and provider. Repeated failures may
require backoff, particularly for rate-limited cloud services. A subsequent
successful operation should clear the corresponding active health issue.

Each distinct issue should have a stable identity, allowing Solala to track
its first occurrence, latest occurrence and recovery. Log the initial
failure, meaningful changes, occasional summaries of persistent problems
and recovery. Avoid logging identical errors every iteration. Unexpected
exceptions should retain traceback information. The log remains the
authoritative detailed diagnostic record.

System health and master alarm
------------------------------

The user-facing master alarm has **five displayed conditions**, representing
three operational health levels and two distinct loss-of-observability
conditions:

| Condition | Display | Meaning | Diagnostic guidance |
| --- | --- | --- | --- |
| Normal | **NORMAL** | Server reachable, control-loop heartbeat current, no active health issues. | No action required. |
| Degraded | **CAUTION** | Server reachable, heartbeat current, noncritical functionality impaired. | Inspect the alarm details. |
| Critical | **WARNING** | Server reachable, heartbeat current, a critical control operation failed or safe control cannot be confirmed. | Inspect the alarm details and log. |
| Stalled | **WARNING — STALLED** | Server reachable, but the control-loop heartbeat is overdue; current control-loop operation cannot be confirmed. | Check the Solala log; the server remains reachable. |
| Disconnected | **DISCONNECTED — UNKNOWN** | Browser cannot obtain a fresh response from the server, including while awaiting the first response after reconnection. | Check the network connection; displayed log data may be stale. |

**STALLED** means that the server is reachable and reports an overdue
control-loop heartbeat. It does not assert that the control loop has
permanently stopped: an unusually long control step or scheduling delay may
also exceed the timeout. **UNKNOWN** means the browser cannot verify the
server's current state. The browser must not infer STALLED merely because a
server response is late.

The master alarm applies these rules in order:

1. Without a fresh server response, display DISCONNECTED — UNKNOWN.
2. With a fresh server response reporting an overdue control-loop heartbeat,
   display WARNING — STALLED, regardless of previously reported health.
3. Otherwise, display NORMAL, CAUTION or WARNING according to the highest
   active severity reported by ControlHealth.

A restored browser connection alone does not establish current system health.
After reconnection, retain UNKNOWN until a fresh server response is received.
That response may establish STALLED or one of the three operational health
levels. In particular, never restore a previously displayed NORMAL solely
because the network connection has returned.

Control-loop heartbeat and timing
---------------------------------

The control-loop heartbeat records completion of a **control-step attempt**,
not the start of the attempt and not proof of successful hardware control.
Update it after a control step finishes, including when an operational failure
has been caught and reported through ControlHealth. Do not update it for an
unfinished or cancelled step. Retain the iteration-start timestamp separately
for control-loop scheduling.

Heartbeat freshness is assessed independently of the control-step task, so a
suspended control step cannot refresh its own heartbeat. The existing overdue
hysteresis is intentional: a short delay need not immediately change the
displayed state. Use `Constants.OVERDUE_THRESHOLD` instead of coupling the
overdue test to `Constants.LOOP_TIME`:

```python
if overdue > Constants.OVERDUE_THRESHOLD.total_seconds():
    # The control-loop heartbeat is overdue.
```

The intended configuration is `LOOP_TIME = 5 seconds`,
`OVERDUE_THRESHOLD = 5 seconds` and `CONTROL_DURATION = 11 seconds`.
Maintain the invariant:

```text
LOOP_TIME + OVERDUE_THRESHOLD < CONTROL_DURATION
```

The overdue calculation must consistently account for the normal loop
interval and the completion-based heartbeat. The intermediate hysteresis
region may retain the previous displayed operational indication while the
server remains reachable; it must not override a known disconnection.

User interface
--------------

The master alarm should remain visible across tabs. Normal operation should
be reassuring and unobtrusive. CAUTION and WARNING should be conspicuous,
but should not generate repeated pop-ups, sounds or notifications.

Selecting the alarm should reveal active issues in plain language, ordered
by severity, including relevant timestamps and occurrence counts, with access
to the existing Log tab. For STALLED, direct the user to the log; for UNKNOWN,
explain that the connection should be checked and displayed log data may be
stale.
Resolved issues should disappear from the active alarm automatically while
remaining in the log. Acknowledgement is not required initially and must
never be confused with recovery.

Responsibilities and implementation direction
---------------------------------------------

- **Control loop:** Decides which actions are safe, isolates operation
  failures, preserves user intent, and reports outcomes.
- **Delegates:** Report genuine failures and enforce their command and
  verification contracts; they must not conceal errors with fabricated
  success values.
- **ControlHealth:** Tracks active issues, severity, repetition and recovery
  without making hardware control decisions. It does not detect a stalled
  control loop or browser disconnection.
- **Control loop:** Records completion of control-step attempts as a heartbeat,
  independently of whether the attempt reported an operational failure.
- **Server:** Reports current operational health and heartbeat freshness.
- **Browser/GUI:** Determines whether a fresh server response is available,
  applies the five-state precedence rules and presents the persistent alarm.
- **Log:** Retains technical failure and recovery details.

The precise severity assigned to individual failures, retry schedules and
command reconciliation procedures remain implementation decisions to be
established and tested as this policy is implemented.

