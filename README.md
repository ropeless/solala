Solala
======

Solala is a Python package for controlling solar power inverters and battery.

This is currently a personal project being shared in case it is useful to others.

The aim of the project is to provide:
  - datatype-aware reading and writing of registers using high-level register names
    potentially using multiple Modbus devices with multiple IP addresses
  - high-level inverter and battery status and control
  - high-level power pricing API
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

Getting Started
===============

See the demonstration scripts in the `src/solala_demo` directory.
A web app can be started using the `src/solala_demo/demo_server.py` script.

For the demos, private constants are declared in a file `local_config.py`
which needs to be in your Python path. An example is provided in the file
`src/solala_demo/_example_local_config.py`.

License
=======

MIT license (see the file `LICENSE.txt`).

