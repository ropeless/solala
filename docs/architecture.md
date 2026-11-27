Software Architecture and Design
================================

Solala separates the control policies from the hardware and external services
used to implement them. The main components are:

- **Control loop** (`../src/solala/control`): Coordinates device connections,
  reads system status and electricity prices, evaluates the configured battery
  and inverter policies, and applies the resulting controls. It also provides
  asynchronous APIs used by the web interface.

- **Delegates** (`src/solala/delegates/`): Abstract interfaces isolate the control
  loop from specific devices and providers. `PowerController` manages inverter
  and battery status and commands; `PowerPricer` supplies current and forecast
  electricity prices; `SolarForecaster` supplies weather-based solar forecasts;
  and `PowerConsumer` exposes monitored electrical loads. Concrete
  implementations include Modbus/Fronius, Amber, Open-Meteo, Tesla Wall
  Connector, Tuya and Matter (via Matter Server) integrations, alongside dummy
  implementations for testing and demos.

- **Register abstraction** (`src/solala/register.py`): Provides typed,
  asynchronous access to named registers. The Modbus implementation maps
  those names to device registers, allowing the higher-level code to work
  without hard-coding register addresses throughout the application.

- **Persistence** (`src/solala/database/`): Uses PostgreSQL via asynchronous
  Psycopg connections to store power measurements.
  Database access is kept separate from the UI and device implementations.

- **Web interface** (`src/solala/server/`): Uses NiceGUI to display live power
  flows, forecasts, charts, controls, status, registers and logs. Tab-specific
  updater objects subscribe to control-loop or database notifications.
  `PageSession` owns the listeners, tasks, timers and clean-up callbacks for
  the currently displayed tab.

  Initial loads, loop notifications and date selections share one listener
  adapter per updater. It runs one refresh at a time and coalesces overlapping
  requests into one pending refresh. Closing the page cancels and drains the
  active refresh and discards pending work, including notifications from stale
  listener snapshots.

  Date-driven updaters discard results superseded by a newer selection.
  The date navigator assigns dates to the carousel slides before awaiting
  browser state persistence. Each slide schedules its refresh with its page session.
  Listener failures are logged as refresh errors. A later notification can
  retry, and the control and database loops continue independently.

- **Configuration** (`src/solala/settings.py`): Defines typed connection and
  application settings, including the selected delegate implementations.

### Conceptual units and information flow

![Solala information flow between the browser, GUI server, control loop,
delegates, database loop, and master alarm](images/solala-information-flow.png)

The browser is the operator's entry point. Through the GUI server, the operator
can view system data and select battery and inverter modes and policies. A mode
specifies the requested operating state. A policy determines whether the
operator selects that state manually or Solala selects it automatically. On
each control step, the loop evaluates the configured policies and sends battery
and inverter commands through the power controller. The current buy and feed-in
prices drive the automatic policies shown here.
See [Control modes and policies](control.md) for more details.

Delegates give Solala a common interface to networked devices and services.
The power controller provides battery and inverter telemetry, the power pricer
provides current and forecast prices, the solar forecaster provides weather-based
solar forecasts, and each named power consumer represents a monitored load.
The GUI draws on these sources for live status, forecasts, and register views.
The database loop periodically records measurements in PostgreSQL when logging
is enabled, and the GUI retrieves those measurements for historical views.

The arrows summarise information flow. The GUI fetches data through the control
API, including database history, and loop notifications prompt subscribed views
to refresh. Register values are read on demand. Each stored measurement combines
power readings, current prices, the previous control mode and policies, and
selected solar forecast data. The forecast views use separate requests for
price and solar forecasts.

The health monitoring and master alarm boxes describe responsibilities. The
master alarm is part of the GUI and uses active health issues and the age of the
control-step completion heartbeat. The browser can also detect that its server
connection has dropped. These signals describe what Solala can observe. Actual
equipment behaviour depends on device capabilities and configuration.
See [Error handling and recovery](error_handling.md#system-health-and-master-alarm) for more details.

### Connection settings and reporting

Delegate factories and the database pool factory must pass every constructor
argument explicitly. Define user-configurable options and their defaults in
the connection settings model. The factory derives any remaining arguments,
such as device roles and resolved addresses, from those settings. Constructor
defaults may still serve callers that instantiate a delegate directly.

`get_connection_info()` must report the effective values passed to the
constructor, including defaults and derived values. Represent connection
objects through their JSON-compatible connection details, such as the Modbus
device map. Omit empty MAC addresses and all secrets, including passwords,
tokens, keys, and secrets nested inside other arguments. Simulated failure
reports include the exception type and omit the exception message.

For example, Modbus settings default `power_control_slaves` to `False`.
PostgreSQL settings default `min_pool_size` to `2` and `max_pool_size` to
`8`. The factories pass these values explicitly, and the connection reports
show the values in use.

Control settings updates and controller, pricer, and forecaster connection
changes capture settings under the connections and control-settings locks and
queue each snapshot before releasing the connections lock. A queued save waits
for earlier saves and writes the file in a worker thread. Callers wait for their
write attempts without holding either state lock.
Successful replacement writes the replacement once. Explicit disconnect saves
the disconnected configuration. If replacement register discovery fails after
the old controller is detached, the recovery path also saves the disconnected
state through the worker thread before reporting the replacement failure.

Database connection changes queue the settings snapshot after draining the old
pool. The database lifecycle lock serializes pool changes through capture and
queueing. It is released before the write, so shutdown can close the pool while
the write is pending.

Startup uses the same write path for its final save. It enables persistence
after the saved or supplied configuration has been applied successfully.

Consumer registration prepares its settings snapshot before publishing the
manager, then writes it off the event loop after releasing the connections
lock. The registered consumer owns its worker while the save is in progress.
Explicit consumer disconnect also writes off the event loop after releasing
the connections lock. The consumer name remains reserved through the save
and manager close.

Shutdown captures pending explicit removals before disabling persistence and
detaching the remaining delegates. Settings writes run outside the connections
lock and may overlap resource cleanup. The deadline limits the wait for
resource cleanup. Shutdown waits for pending settings writes before returning,
even if that deadline expires.

### Runtime and data flow

The server runs Uvicorn/NiceGUI and the control loop concurrently on a single
`asyncio` event loop. The control loop obtains data through the delegates,
applies the selected control policies, and notifies subscribed UI listeners.
A separate database loop records measurements and notifies listeners that
display historical data. The browser communicates with NiceGUI; it does not
connect directly to the inverter or the database.

The GUI reads register values on demand for display. The control loop
does not collect register history.
The Registers page explicitly requests consumer register discovery.
Register bank lookups use published definitions and reuse the combined bank
until a delegate changes or publishes its definitions.
When a consumer has no status reading available, its status registers raise
`RegisterValueUnavailable`. The Registers page displays those names without
values or tracebacks. Consumer health reporting logs completed device
failures and recoveries.

Each power consumer manager runs one worker for status reads and register
discovery. The worker waits for client demand and coalesces requests for
the same operation while a read is pending. Callers receive available
results immediately while the worker handles delegate I/O.
Consumer health is updated when a current worker completes a status or
discovery attempt. Pending reads do not raise a health issue. Operational
failures and recovery are logged per consumer and operation.
Disconnecting a consumer removes it from the active connections before
waiting for its worker to close. The wait happens outside the shared
connections lock. Connecting with an active or closing name fails. The
client must wait for disconnect to complete before reusing a name.
Control-loop shutdown stops the database logging task, closes consumer workers
concurrently, and waits for any disconnects already in progress. It also closes
the controller, pricer, forecaster, and database pool. The pool stops accepting
new borrows and drains existing ones. Shutdown logs each close outcome and
keeps the saved configuration for the next run.
The server owns the control-loop task. During graceful shutdown, the FastAPI
lifespan stops and awaits it before Uvicorn replays the termination signal.
If Uvicorn exits before lifespan shutdown, the server cancels and awaits the
control-loop task before the event loop closes.
The HTTP server uses its grace period to decide when to request cancellation
of the control-loop task. The control loop has a separate ten-second budget
solely for closing delegate connections and stopping database logging.
Control-loop housekeeping, including acquiring the connections lock and
detaching delegates, happens before this timer starts. Pending settings writes
are drained outside the budget, before the control loop returns. If the
delegate cleanup budget expires, Solala requests cancellation and logs the
closes that are still pending. Blocking I/O in a worker thread can outlive the
deadline. Tuya LAN limits each request to one connection attempt, uses its
configured socket timeout, and avoids resending the payload to reduce drain
time.

Startup defers settings writes until a complete configuration succeeds. If
applying saved settings fails and fallback settings are available, startup
closes the open connections before applying the fallback.

### Design principles

- **Provider independence:** Control policies depend on delegate interfaces
  rather than on individual vendor APIs. Dummy delegates permit operation
  without physical hardware.

- **Asynchronous coordination:** Device access, forecasting, database operations
  and UI updates use asynchronous interfaces. The server and control loop share
  one event loop rather than requiring separate application threads.

- **Explicit lifecycle management:** Connections are opened and closed through
  the control-loop APIs. UI subscriptions and background tasks are tied to a
  page session and cleaned up when the user switches tabs or disconnects.

- **Typed data and configuration:** Python type annotations, dataclasses and
  Pydantic models describe register values, measurements and settings.

### Error handling and recovery

Tuya Cloud HTTP requests use explicit connect and read timeouts. Matter
applies one deadline to connection setup and the full command exchange,
including time spent processing unrelated events.

The intended policy for failure isolation, safe control retries, operational
health and master alarms is documented in [Error Handling and Recovery](error_handling.md).
These behaviours are being implemented incrementally; the policy describes
the target design rather than asserting complete implementation.
