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

Control Modes and Policies
==========================

Solala distinguishes between a **mode**, which describes the operating state
requested for a device, and a **policy**, which determines whether that mode
is selected manually or adjusted automatically.

Battery and inverter modes and policies are configured independently:

- **Battery modes:** Enable (normal charging and discharging), Disable,
  Force Charge, Force Discharge, Charge Only and Discharge Only.
- **Inverter modes:** Enable (normal operation), Disable (stop solar power
  production) and Zero Export (minimise power exported to the grid).
- **Manual policy:** Solala uses the mode selected by the user.
- **Automatic battery policy — Cheap Charge:** Switches to Force Charge
  when the electricity purchase price is sufficiently low, and stops forced
  charging when the price rises above a separate threshold.
- **Automatic inverter policy — Negative Feed-in Zero Export:** Selects
  Zero Export when the feed-in price falls below the configured threshold,
  and re-enables normal operation when it rises above a separate threshold.

The separate start/stop and disable/enable price thresholds allow policies
to avoid repeatedly switching modes when prices fluctuate near a boundary.
For example, a negative feed-in tariff can trigger Zero Export without
requiring the user to disable the inverter manually.

The mode, policy and thresholds are represented together by `ControlMode`
in `src/solala/control_loop/modes_and_policies.py`. The control loop
evaluates these settings and sends commands through the `PowerController`
interface. Actual device behaviour depends on the inverter and battery
capabilities and configuration.

Supported Integrations and Limitations
======================================

Solala is a personal project developed for a particular home solar installation.
It is shared for experimentation and adaptation rather than as a turnkey
solution for arbitrary systems.

- **Inverters and batteries:** The supplied power-controller implementation
  targets Fronius inverters through Modbus and SunSpec registers. Support for
  other manufacturers may require another `PowerController` implementation.
  Compatibility with other Fronius models and firmware versions has not been
  established.

- **Multiple inverters:** The Modbus controller supports a master inverter and
  optional slave inverters. Battery control is performed through the master.
  Power curtailment is applied to the master by default; controlling slaves
  is configurable and depends on the installation's capabilities.

- **Electricity prices:** Amber is the implemented live pricing provider.
  A dummy pricing provider is available for demonstrations.

- **Forecasting and monitored loads:** Open-Meteo supplies solar forecasts.
  Optional power-consumer integrations include Tesla Wall Connector and Tuya
  devices; their availability depends on device compatibility and configuration.

- **Web interface:** NiceGUI provides monitoring, forecasts, historical charts,
  diagnostics and manual or policy-driven controls. The interface is designed
  for this project and is not a general-purpose installation or administration
  tool.

- **Network access:** The server needs network connectivity to the inverter
  and other configured devices; it does not necessarily have to run on the
  same physical LAN if routing and device access are correctly configured
  (e.g., via a VPN).
  Remote browser access should be secured appropriately.

- **Persistence:** Historical measurement storage requires a configured
  PostgreSQL database. The dummy demonstration runs without database writes.

Inverter control affects real electrical equipment. Validate compatibility,
permissions and control behaviour on your installation before relying on
automatic policies.

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

Development and Testing
=======================

Solala's source code is under `src/solala/`, demonstration entry points are
under `src/solala_demo/`, and tests are under `tests/`.

### Run the tests

The tests use Python's built-in `unittest` framework. From the repository
root, with `src/` on `PYTHONPATH` and the project dependencies installed:

```sh
poetry run python -m unittest discover -s tests
```

Some integrations communicate with external hardware or services. Use the
dummy implementations for development when those dependencies are unavailable,
and do not assume that running tests exercises real-device behaviour.

### Add a device or service integration

The control loop depends on abstract delegate interfaces rather than vendor
APIs. To introduce another implementation:

1. Choose the relevant interface under `src/solala/delegates/`:
   `PowerController` for inverter and battery control, `PowerPricer` for
   electricity prices, `SolarForecaster` for solar predictions, or
   `PowerConsumer` for monitored electrical loads.
2. Implement the interface's methods, including asynchronous operations,
   connection information and resource cleanup. Follow an existing dummy
   or concrete implementation as a reference.
3. Add the corresponding connection configuration and delegate construction
   to the settings and connection-handling code, so the control loop can
   select the implementation.
4. Add tests for normal operation, failures and cleanup. Test with dummy
   dependencies before connecting real equipment.

The interfaces and their method docstrings define the expected behaviour.
In particular, keep device-specific protocols inside delegates rather than
introducing vendor-specific logic into the control loop or web interface.

GUI User Hints
==============
On the landing page, the "Power" panel shows a live infographic of power and pricing information.

Click the infographic "grid" icon to see the forecast of power prices.

Click the infographic "sun" icon to see the forecast of solar power.


More Information
================

For questions about Solala, further technical information, or development
inquiries, contact the lead developer at [barry@ropeless.com](mailto:barry@ropeless.com).

License
=======

MIT license (see the file `LICENSE.txt`).

