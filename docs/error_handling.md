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
three operational health levels plus two loss-of-observability conditions:

| Condition | Display | Meaning |
| --- | --- | --- |
| Normal | **NORMAL** | Control loop responsive; no active faults known. |
| Degraded | **CAUTION** | Noncritical functionality is impaired. |
| Critical | **WARNING** | A critical control operation has failed or safe control cannot be confirmed. |
| Stalled | **WARNING — STALLED** | Control loop is unresponsive; monitoring and control cannot be trusted. |
| Disconnected | **DISCONNECTED — UNKNOWN** | Browser cannot contact the server; current system state is unknown. |

The most severe active operational issue determines NORMAL, CAUTION or
WARNING. **STALLED overrides the reported operational health**: a stalled
loop cannot reliably report its own condition. The GUI must assess loop
responsiveness independently of the control iteration, using an appropriate
heartbeat timeout. **DISCONNECTED overrides every other displayed condition**
in the browser because it can no longer verify any current server status.
After reconnection, the browser must obtain fresh status before displaying
NORMAL.

Stalled and disconnected are different: the former means the server is
reachable but its control loop is not responsive; the latter means the
browser cannot determine whether the server or control loop is functioning.
Neither should leave a reassuring stale NORMAL indication on screen.

User interface
--------------

The master alarm should remain visible across tabs. Normal operation should
be reassuring and unobtrusive. CAUTION and WARNING should be conspicuous,
but should not generate repeated pop-ups, sounds or notifications.

Selecting the alarm should reveal active issues in plain language, ordered
by severity, with relevant details and access to the existing Log tab.
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
- **ControlHealth (proposed):** Tracks active issues, severity, repetition
  and recovery without making hardware control decisions.
- **Server/GUI:** Presents operational health, independently detects a
  stalled loop, and displays DISCONNECTED when the browser loses contact.
- **Log:** Retains technical failure and recovery details.

The precise severity assigned to individual failures, retry schedules,
command reconciliation procedures and health API are implementation
decisions to be established and tested as this policy is implemented.

