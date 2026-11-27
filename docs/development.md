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
   select the implementation. Follow the [connection settings and reporting
   policies](architecture.md#connection-settings-and-reporting) when adding
   constructor arguments, defaults, or connection report fields.
4. Add tests for normal operation, failures and cleanup. Test with dummy
   dependencies before connecting real equipment.

The interfaces and their method docstrings define the expected behaviour.
In particular, keep device-specific protocols inside delegates rather than
introducing vendor-specific logic into the control loop or web interface.
