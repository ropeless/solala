Solala
======

Solala is a Python package and web app for controlling solar power inverters and battery.

This is currently a personal project being shared in case others find it useful.

![Solala Power dashboard](doc_images/screenshot%20-%20Power.PNG)

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
- Battery Manual: Charge Only.
- Battery Manual: Discharge Only.
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
  Connector and Tuya integrations, alongside dummy implementations for testing and demos.

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

### Prerequisites and installation

Solala requires **Python 3.13 or later**. The repository uses Poetry to manage
dependencies (see `pyproject.toml`); Poetry is configured for dependency
management rather than packaging the project as an installable distribution.

Clone the repository and install its dependencies:

```sh
git clone https://github.com/ropeless/solala.git
cd solala
poetry install
```

The demonstration modules are under `src/`. Include that directory in
`PYTHONPATH` when running them from the repository checkout.

### Configure the demos

Copy `src/solala_demo/_example_local_config.py` to a file named
`local_config.py` in a directory on your Python path, and edit the values
for your environment. The demo scripts import this configuration through
`solala.utils.local_config_help`.

At a minimum, check `SERVER_HOST`, `SERVER_PORT`, `OUT`,
`DUMMY_SETTINGS_PATH`, `PANEL_CAPACITY` and `INVERTER_LIMIT` before
running the dummy demo. Set `DUMMY_SETTINGS_PATH` to a writable location
and ensure its parent directory exists.

The example file also contains placeholder inverter addresses, API tokens,
device credentials and database settings for the real-hardware demo.
**Do not commit a populated `local_config.py` containing credentials.**

### Run without hardware

The dummy server uses simulated controller, pricing, consumer and solar
forecast implementations. It does not require an inverter or an Amber
account, and it disables database writes.

With `src/` and the directory containing `local_config.py` on
`PYTHONPATH`, run:

```sh
poetry run python -m solala_demo.demo_dummy_server
```

Then open the address configured by `SERVER_HOST` and `SERVER_PORT`
(for example, `http://localhost:8080/`).

The demo loads an existing dummy settings file when available. Set
`FORCE_SETTINGS = True` in `local_config.py` to apply the demo's
initial dummy connections instead of previously saved settings.

### Run with real hardware and services

The real-hardware demonstration is
`src/solala_demo/demo_server.py`. Its sample configuration connects to
Fronius inverters over Modbus, Amber for electricity pricing, Open-Meteo
for solar forecasting, Tesla and Tuya power consumers, and PostgreSQL
for historical data.

Configure the corresponding values in `local_config.py`, including
inverter addresses, the Amber API token and NMI, solar installation
parameters, and any consumer or database credentials. Edit
`demo_server.py` if your system does not use all of these integrations.

Run it from the repository checkout:

```sh
poetry run python -m solala_demo.demo_server
```

The `scripts/run_solala.sh` script is an example deployment script with
machine-specific paths and an automatic `git pull`; review and adapt it
before use.

**Caution:** The real-hardware demo can send commands that change inverter
and battery operation. Confirm device settings and control policies before
enabling automatic control.

GUI User Hints
==============
On the landing page, the "Power" panel shows a live infographic of power and pricing information.

Click the infographic "grid" icon to see the forecast of power prices.

Click the infographic "sun" icon to see the forecast of solar power.


License
=======

MIT license (see the file `LICENSE.txt`).

