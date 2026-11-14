Solala
======

Solala is a Python package and web app for controlling solar power inverters and battery.

This is currently a personal project being shared in case others find it useful.

The aim of the project is to provide:

- datatype-aware reading and writing of Modbus registers using high-level register names
  potentially using multiple Modbus devices with multiple IP addresses
- high-level inverter and battery status and control
- high-level power pricing and forecasting API
- high-level system control and control policies
- a web app for monitoring and controlling the system.

Here are the implemented control policies.

- Battery Manual: Enable (the normal condition, allow charge and discharge).
- Battery Manual: Disable (neither charge nor discharge is allowed).
- Battery Manual: Force Charge.
- Battery Manual: Force Discharge.
- Battery Auto: Cheap Energy ⇒ Force Charge (force charge if energy is cheap).
- Inverter Manual: Enable (the normal condition, allow export to the grid).
- Inverter Manual: Disable (stop inverter providing solar power).
- Inverter Manual: Zero Export (try to not export to or import from the grid).
- Inverter Auto: Negative Feed-in Tariff ⇒ Zero Export (force zero export if the feed-in tariff is negative).

As it is a personal project, there are a few limitations.

- There is only support for Fronius GEN4 inverters.
- There is only support for Amber as the power price provider.
- The web app is very basic.
- The web app needs to run on the same LAN as the inverters.

Software Architecture and Design
================================

Solala separates the control policies from the hardware and external services
used to implement them. The main components are:

- **Control loop** (`src/solala/control_loop/`): Coordinates device connections,
  reads system status and electricity prices, evaluates the configured battery
  and inverter policies, and applies the resulting controls. It also provides
  asynchronous APIs used by the web interface.
- **Delegates** (`src/solala/delegates/`): Abstract interfaces isolate the control
  loop from specific devices and providers. `PowerController` manages inverter
  and battery status and commands; `PowerPricer` supplies current and forecast
  electricity prices; `SolarForecaster` supplies weather-based solar forecasts;
  and `PowerConsumer` exposes monitored electrical loads. Concrete
  implementations include Modbus/Fronius, Amber, Open-Meteo, Tesla Wall
  Connector and Tuya integrations, alongside dummy implementations for demos.
- **Register abstraction** (`src/solala/registers.py`): Provides typed,
  asynchronous access to named registers. The Modbus implementation maps
  those names to device registers, allowing the higher-level code to work
  without hard-coding register addresses throughout the application.
- **Persistence** (`src/solala/database/`): Uses PostgreSQL via asynchronous
  Psycopg connections to store power measurements and register history.
  Database access is kept separate from the UI and device implementations.
- **Web interface** (`src/solala/server/`): Uses NiceGUI to display live power
  flows, forecasts, charts, controls, status, registers and logs. Tab-specific
  updater objects subscribe to control-loop or database notifications.
  `PageSession` owns the listeners, tasks, timers and cleanup callbacks for
  the currently displayed tab.
- **Configuration** (`src/solala/settings.py`): Defines typed connection and
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

Getting Started
===============

See the demonstration scripts in the `src/solala_demo` directory.

A web app can be started using the `src/solala_demo/demo_server.py` script or `scripts/run_solala.sh`.
Those scripts will start the web app with real connections to the inverters and power pricer.
You can also start the web app with dummy connections using the `src/solala_demo/demo_dummy_server.py` script.

For the demos, private constants are declared in a file `local_config.py`
which needs to be in your Python path. An example is provided in the file
`src/solala_demo/_example_local_config.py`.

GUI User Hints
==============
On the landing page, the "Power" panel shows a live infographic of power and pricing information.

Click the infographic "grid" icon to see the forecast of power prices.

Click the infographic "sun" icon to see the forecast of solar power.


License
=======

MIT license (see the file `LICENSE.txt`).

