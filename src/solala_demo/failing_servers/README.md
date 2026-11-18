# Failing Solala demo servers

Run one scenario at a time from the project environment, for example:

```bash
python -m solala_demo.failing_servers.solar_forecast_failure
```

Available scenarios:

- `solar_forecast_failure`: persistent solar forecast timeout
- `intermittent_solar_failure`: 50% chance of solar forecast timeout on each request
- `controller_failure`: persistent power controller status timeout
- `pricer_failure`: persistent current-price timeout
- `consumer_failure`: persistent example-consumer status timeout
- `combined_failure`: simultaneous controller and example-consumer status timeouts

Each module has a `main()` entry point. The common runner forces the
scenario settings so existing saved dummy settings do not override them.
It disables database writes, but uses the configured dummy settings path;
run only in a development/demo environment. Stop the running server before
starting another scenario on the same port.

The intermittent scenario is probabilistic; a successful request is not
guaranteed immediately after a failure. The master alarm's behaviour depends
on the control loop's error handling and recovery policy.
