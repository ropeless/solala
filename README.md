Solala
======

Solala is a Python package and web app for monitoring and controlling home solar
power inverters and batteries. It is a personal project shared in case others
find it useful.

![Solala Power dashboard](docs/images/screenshot%20-%20Power.PNG)

Features
========

- Monitor solar generation, household consumption, battery usage and grid power.
- Control inverter and battery operating modes manually or through price-driven policies.
- Read and write typed, named Modbus registers, including across multiple devices.
- View electricity price and solar generation forecasts, historical charts and diagnostics.
- Use a NiceGUI web interface, with dummy integrations available for development and demos.

Supported Integrations and Limitations
======================================

Solala is designed for a particular home installation, not as a turnkey
solution for every solar system.

- **Inverters and batteries:** Fronius through Modbus/SunSpec, with master and
  optional slave inverters. Compatibility with other models and firmware is
  not established; slave power curtailment depends on configuration.
- **Electricity prices and forecasts:** Amber for live electricity pricing
  and Open-Meteo for solar forecasting.
- **Other devices:** Optional Tesla Wall Connector and Tuya integrations.
- **History:** PostgreSQL for measurement storage.
- **Networking:** The server needs access to configured devices, locally or
  through suitable network routing; remote browser access should be secured.

**Caution:** Solala can change inverter and battery operation. Validate
compatibility and control behaviour before using automatic policies.

Quick Start
===========

Solala requires Python 3.13 or later and uses Poetry for dependency management.

```sh
git clone https://github.com/ropeless/solala.git
cd solala
poetry install
```

To try the web app without solar hardware, prepare a `local_config.py` from
`src/solala_demo/_example_local_config.py`, set the required local paths,
and make `src/` and the configuration directory available on `PYTHONPATH`.
Then run:

```sh
poetry run python -m solala_demo.demo_dummy_server
```

See the [Getting Started guide](docs/getting_started.md) for configuration,
step-by-step instructions and running with real hardware.

Documentation
=============

- [Getting Started](docs/getting_started.md) — installation, configuration,
  demo servers and web interface hints.
- [Control Modes and Policies](docs/control.md) — manual modes, automatic
  policies and price thresholds.
- [Software Architecture and Design](docs/architecture.md) — components,
  delegates, data flow and design principles.
- [Development and Testing](docs/development.md) — tests and adding new
  hardware or service integrations.

More Information
================

For questions about Solala, further technical information, or development
inquiries, contact the lead developer at [barry@ropeless.com](mailto:barry@ropeless.com).

License
=======

MIT license (see the file [LICENSE.txt](LICENSE.txt)).
