Getting Started
===============

### Prerequisites and installation

Solala requires **Python 3.13 or later**. The repository uses Poetry to manage
dependencies (see `../pyproject.toml`); Poetry is configured for dependency
management rather than packaging the project as an installable distribution.

Clone the repository and install its dependencies:

```sh
git clone https://github.com/ropeless/solala.git
cd solala
poetry install
```

The demonstration modules are under `../src/`. Include that directory in
`PYTHONPATH` when running them from the repository checkout.

### Configure the demos

Copy `../src/solala_demo/_example_local_config.py` to a file named
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

With `../src/` and the directory containing `local_config.py` on
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
`../src/solala_demo/demo_server.py`. Its sample configuration connects to
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

The `../scripts/run_solala.sh` script is an example deployment script with
machine-specific paths and an automatic `git pull`; review and adapt it
before use.

**Caution:** The real-hardware demo can send commands that change inverter
and battery operation. Confirm device settings and control policies before
enabling automatic control.

### Using the web interface

On the landing page, the "Power" panel shows a live infographic of power and pricing information.

Click the infographic "grid" icon to see the forecast of power prices.

Click the infographic "sun" icon to see the forecast of solar power.
