Getting Started
===============

### Prerequisites and installation

Solala requires **Python 3.13 or later**. The repository uses Poetry to manage
dependencies (see `pyproject.toml`); Poetry is configured for dependency
management but not for packaging the project as an installable distribution.

Clone the repository and install its dependencies:

```sh
git clone https://github.com/ropeless/solala.git
cd solala
poetry install
```

The demonstration scripts are under `src/`. Include that directory in
`PYTHONPATH` when running them from the repository checkout.

### Run without hardware

The dummy server simulates an inverter, electricity prices, a power consumer,
and a solar forecast. It runs without hardware, service credentials, or a database.

1. Save this example as `local_config.py` in the checkout root, next to
   `pyproject.toml`. Back up any existing `local_config.py` before replacing it.
   Keep your local configuration out of version control.

   ```python
   from secrets import token_hex

   SERVER_HOST = '127.0.0.1'
   SERVER_PORT = 8080
   SOLALA_STORAGE_SECRET = token_hex(32)

   PANEL_CAPACITY = 9360
   INVERTER_LIMIT = 8000

   DUMMY_SETTINGS_PATH = None
   FORCE_SETTINGS = False

   APP_LOG_LEVEL = 'INFO'
   DEMO_LOG_FORMAT = '%(levelname)s: %(message)s'
   ```

   The example disables settings persistence and generates a fresh storage
   secret each time the server starts.

2. Start the server from the checkout root.

   **PowerShell**

   ```powershell
   $env:PYTHONPATH = 'src'
   poetry run python -m solala_demo.demo_dummy_server
   ```

   **POSIX shell**

   ```sh
   PYTHONPATH=src poetry run python -m solala_demo.demo_dummy_server
   ```

3. Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/) in your browser.
   Press Ctrl+C in the terminal to stop the server.

### Run with real hardware and services

A real-hardware demonstration is provided by `src/solala_demo/demo_server.py`.
Its sample configuration connects to
Fronius inverters over Modbus, Amber for electricity pricing, Open-Meteo
for solar forecasting, Tesla, Tuya and Matter power consumers, and
PostgreSQL for historical data.

Copy the [full configuration template](examples/example_local_config.py) to a directory
on your Python path as `local_config.py`. Replace the sample values with your
inverter addresses, Amber API token and NMI, solar installation parameters,
and any consumer or database credentials. The demos also read environment
variables for settings absent from `local_config.py`.
Keep your populated configuration out of version control. Edit
`demo_server.py` if your system does not use all of these integrations.

For Matter devices, run a compatible Matter Server separately and commission
its devices before starting Solala. Set `MATTER_SERVER_HOST` and
`MATTER_SERVER_PORT` to the Matter Server WebSocket endpoint, and configure
`MATTER_DEVICE_IDS` as a dictionary mapping commissioned node IDs to Solala
consumer names, for example:

```python
MATTER_SERVER_HOST = '192.168.0.203'
MATTER_SERVER_PORT = 5580
MATTER_DEVICE_IDS = {1: 'plug_1'}
```

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

### Using the web interface

On the landing page, the "Power" panel shows a live infographic of power and pricing information.

Click the infographic "grid" icon to see the forecast of power prices.

Click the infographic "sun" icon to see the forecast of solar power.
