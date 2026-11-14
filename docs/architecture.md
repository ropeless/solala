Software Architecture and Design
================================

Solala separates the control policies from the hardware and external services
used to implement them. The main components are:

- **Control loop** (`../src/solala/control_loop/`): Coordinates device connections,
  reads system status and electricity prices, evaluates the configured battery
  and inverter policies, and applies the resulting controls. It also provides
  asynchronous APIs used by the web interface.

- **Delegates** (`../src/solala/delegates/`): Abstract interfaces isolate the control
  loop from specific devices and providers. `PowerController` manages inverter
  and battery status and commands; `PowerPricer` supplies current and forecast
  electricity prices; `SolarForecaster` supplies weather-based solar forecasts;
  and `PowerConsumer` exposes monitored electrical loads. Concrete
  implementations include Modbus/Fronius, Amber, Open-Meteo, Tesla Wall
  Connector and Tuya integrations, alongside dummy implementations for testing and demos.

- **Register abstraction** (`../src/solala/registers.py`): Provides typed,
  asynchronous access to named registers. The Modbus implementation maps
  those names to device registers, allowing the higher-level code to work
  without hard-coding register addresses throughout the application.

- **Persistence** (`../src/solala/database/`): Uses PostgreSQL via asynchronous
  Psycopg connections to store power measurements and register history.
  Database access is kept separate from the UI and device implementations.

- **Web interface** (`../src/solala/server/`): Uses NiceGUI to display live power
  flows, forecasts, charts, controls, status, registers and logs. Tab-specific
  updater objects subscribe to control-loop or database notifications.
  `PageSession` owns the listeners, tasks, timers and cleanup callbacks for
  the currently displayed tab.

- **Configuration** (`../src/solala/settings.py`): Defines typed connection and
  application settings, including the selected delegate implementations.

### Runtime and data flow

The server runs Uvicorn/NiceGUI and the control loop concurrently on a single
`asyncio` event loop. The control loop obtains data through the delegates,
applies the selected control policies, and notifies subscribed UI listeners.
A separate database loop records measurements and notifies listeners that
display historical data. The browser communicates with NiceGUI; it does not
connect directly to the inverter or the database.

```text
  Fronius / Modbus ── PowerController ──┐
  Amber API ───────── PowerPricer ──────┤
  Open-Meteo ──────── SolarForecaster ──┼── Control loop / policies
  Monitored loads ─── PowerConsumer ────┘            │
                                                     ├── Device commands
                                                     ├── PostgreSQL history
                                                     └── NiceGUI listeners
                                                               │
                                                          Web browser
```

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
