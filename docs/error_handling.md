Error Handling and Recovery Policy
==================================

Status
------

The control loop isolates handled failures, and `ControlHealth` tracks the
operational issues that callers report. Lifecycle caches manage refresh
failures, and the master alarm displays the status derived from health
reports, heartbeat freshness and browser connectivity.

Each hardware delegate must verify command outcomes and reconcile uncertain
device state when required by its command contract. The master alarm reflects
the evidence available to Solala.

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

The control loop isolates handled operational failures so that independent
work can continue within an iteration. A failed subsystem does not by itself
prevent unrelated work: for
example, a failed battery command should not prevent an independent inverter
command from being attempted when that command is safe.

Errors in individual consumers, forecasts, price services, measurement
persistence and UI listeners are handled at their respective
operation boundaries. Recoverable database failures are handled without
terminating the database loop. A reporting failure is not evidence of a
valid zero measurement or a successful hardware operation.

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

One-shot commands and keep-alive commands
-----------------------------------------

Battery mode commands and inverter ENABLE are **one-shot commands**: the
control loop issues them when a new mode is requested, rather than on every
iteration. If a one-shot command raises an exception, its outcome is uncertain.
The control loop reports the affected mode as **UNKNOWN**, preserves its
selected policy, and records a **WARNING** health issue for that command.
The Status page therefore reports UNKNOWN, and the Power page does not
highlight the failed mode as though it had succeeded. UNKNOWN describes the
command outcome; it is not a measurement of the physical device state.

The control loop remembers the failed attempt separately from the reported
mode so that publishing UNKNOWN does **not** automatically retry the failed
one-shot command. A user can explicitly select a mode again, including the
same mode that failed. Each failed explicit attempt increases the issue's
occurrence count. A subsequent successful mode command updates the reported
mode and clears that command's WARNING. An automatic policy remains selected
through a failure; its next genuinely changed mode request may likewise
trigger a new command, but an unchanged failed request is not retried merely
because another loop iteration runs.

Inverter DISABLE, FIXED_LIMIT and ZERO_EXPORT require **keep-alive commands**
reissued on each control-loop iteration. The reported mode remains the
requested mode even when a keep-alive fails, so the loop continues attempting
the restriction. FIXED_LIMIT also retains the requested percentage and includes
it in the failure diagnostic. The command health issue remains at
WARNING while those attempts fail, and its occurrence count increases with
each failure. A successful keep-alive clears that issue. The displayed mode
in this case represents the **requested restriction**, not proof that the
inverter is obeying it; the WARNING communicates the uncertainty.

This also applies when the previous selection is **MANUAL + UNKNOWN** after a
failed ENABLE command. An explicit manual keep-alive selection supersedes the
earlier one-shot request. If the first keep-alive attempt fails, Solala retains
the new mode and its parameters, reports the uncertain outcome, and attempts
the command again on the next iteration. A later mode selection supersedes
that request. One-shot failure tracking applies only to the request that failed.

Recovery and logging
--------------------

Recoverable operations are retried according to their control-loop or cache
schedule. Rate-limited services require provider-appropriate retry behaviour;
not every delegate implements exponential backoff. A successful recovery
clears the corresponding active health issue when that operation reports success.

`ControlHealth` identifies active issues by stable keys and records severity,
message, first and latest occurrence times, and occurrence count. Repeated
reports increment the count; a successful operation removes its active issue.
Callers use the return value from `report_failure()` to suppress unchanged
error messages where appropriate. The log remains the detailed diagnostic
record, including traceback context for unexpected exceptions.

System health and master alarm
------------------------------

To observe alarm conditions and recovery without hardware, run one of the
[failure demos](README_failing_demos.md).

Operation code reports outcomes with a stable issue key, severity, and
user-facing message. `ControlHealth` tracks active issues, logs new or changed
failures and recovery, and provides immutable snapshots. Diagnostic log
messages and tracebacks are supplied separately from the displayed message.
Health updates and snapshot reads are synchronous on the control event loop.

The persistent master alarm implements **five displayed conditions**. Each has two distinct
interpretations: **user understanding** describes the potential operational
impact in plain language; **system understanding** specifies the evidence
used to select the state. The user interpretation is not a claim that the
suspected hardware condition has been confirmed.

| Display | User understanding | System understanding | Diagnostic guidance |
| --- | --- | --- | --- |
| **LIVE** | Hardware control and reporting appear to be working correctly. | Server reachable, control-loop heartbeat current, no active health issues. | No action required. |
| **CAUTION** | Hardware control is believed to be working, but some reporting or other noncritical functionality is impaired. | Server reachable, heartbeat current, highest active ControlHealth severity is CAUTION. | Inspect the alarm details. |
| **WARNING** | Suspected partial loss of hardware control, or uncertainty about safe control. | Server reachable, heartbeat current, highest active ControlHealth severity is WARNING. | Inspect the alarm details and log. |
| **STALLED** | Suspected total loss of hardware control. | Server reachable, but the control loop does not appear to be running correctly: its completion heartbeat is overdue, possibly because the crucial control-step method is not getting processor time or is waiting indefinitely. | Check the Solala log; the server remains reachable. |
| **DISCONNECTED** | The current condition of the system is unknown. | Browser cannot obtain a fresh response from the server, including while awaiting the first response after reconnection. | Check the network connection; displayed log data may be stale. |

The distinction is particularly important for **STALLED**: its user meaning
expresses the potential consequence, while its system meaning describes
what can actually be detected. An overdue heartbeat does not prove that
hardware control has stopped; a long-running step or scheduling delay can
also cause it. **DISCONNECTED** means the browser cannot verify the server's
current state. The browser must not infer STALLED merely because a server
response is late.

The master alarm selects its state using these precedence rules:

1. The browser displays DISCONNECTED when its socket disconnects or its
   response watchdog expires (6.5 seconds since the last received update).
2. The server reports STALLED when the control-loop heartbeat exceeds
   `Constants.OVERDUE_THRESHOLD`, regardless of active health issues.
3. Otherwise, the server reports LIVE, CAUTION or WARNING according to the
   highest active severity in `ControlHealth`.

A restored socket connection first displays DISCONNECTED. The browser accepts
an operational state only after a subsequent server update. The server sends
updates every two seconds; the browser watchdog checks freshness every second.
The browser does not infer STALLED from network silence.

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

The current configuration is `LOOP_TIME = 5 seconds`,
`OVERDUE_THRESHOLD = 5 seconds` and `CONTROL_DURATION = 11 seconds`.
The timing configuration satisfies the invariant:

```text
LOOP_TIME + OVERDUE_THRESHOLD < CONTROL_DURATION
```

The overdue calculation accounts for the normal loop interval and the
completion-based heartbeat. Once STALLED is reported, the server retains it
while the heartbeat remains overdue, until the control loop catches up.
Browser-side DISCONNECTED takes precedence over any server-reported state.

User interface
--------------

The master alarm remains visible in the page header across tabs. It uses a
coloured light and text label without repeated pop-ups, sounds or notifications.

Selecting the alarm opens the **System Health** dialogue. It displays the
server-confirmed status and active issues in severity order, with descriptions,
first and latest occurrence times, and counts. While open, the dialogue updates
when the health snapshot changes. It provides **Go to Log** and **Close**
controls. STALLED includes guidance to inspect the log. During a browser
disconnection, the header shows DISCONNECTED; an open dialogue may retain stale
server-confirmed details because updates have stopped.

Recovered issues disappear from the active issue list automatically. No
acknowledgement mechanism is implemented; historical details remain in the log.

Implementation responsibilities
-------------------------------

- **Control loop:** Decides which actions are safe, isolates operation
  failures, preserves user intent, reports outcomes, and records completion
  of control-step attempts as a heartbeat even when a handled failure occurs.
- **Delegates:** Report genuine failures and enforce their command and
  verification contracts; they must not conceal errors with fabricated
  success values.
- **ControlHealth:** Tracks active issues, severity, repetition and recovery
  without making hardware control decisions. It does not detect a stalled
  control loop or browser disconnection.
- **Server:** Reports current operational health and heartbeat freshness.
- **Browser/GUI:** Detects socket disconnection and stale server responses,
  overriding the server state with DISCONNECTED when necessary. Presents the
  persistent alarm and its details.
- **Log:** Retains technical failure and recovery details.

**Scope of health reporting:** `ControlHealth` receives explicit failure and
recovery reports from operational call sites. A failed solar forecast refresh
handled by `LifecycleCache` does not automatically create a CAUTION issue:
an unexpired cached forecast may remain available, and cache failures are
logged separately. The master alarm is not an exhaustive inventory of every
transient service error.

**Hardware safety boundary:** Severity assignments, retry schedules and
command reconciliation depend on each operation and delegate. LIVE means
no active issues are currently reported; it is not independent verification
that every physical device is in its requested state. The safety requirements
above continue to apply to hardware integrations.

