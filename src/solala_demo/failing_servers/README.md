# Failing Solala demo servers

Run one scenario at a time from the project environment, for example:

```bash
python -m solala_demo.failing_servers.solar_forecast_failure
```

Available scenarios:

- `solar_forecast_failure`: persistent solar forecast timeout
- `intermittent_solar_failure`: 50% chance of solar forecast timeout on each request
- `controller_failure`: persistent power controller status timeout
- `recovering_controller`: first ten controller status reads fail, then recover
- `pricer_failure`: persistent current-price timeout
- `consumer_failure`: persistent example-consumer status timeout
- `combined_failure`: simultaneous controller and example-consumer status timeouts
- `command_failure`: persistent inverter disable command timeout; exercises WARNING
- `stalled_control_loop`: 18-second battery disable delay; exercises STALLED and recovery

Each module has a `main()` entry point. The common runner forces the
scenario settings so existing saved dummy settings do not override them.
It disables database writes, but uses the configured dummy settings path;
run only in a development/demo environment. Stop the running server before
starting another scenario on the same port.

The intermittent scenario is probabilistic; a successful request is not
guaranteed immediately after a failure. The master alarm's behaviour depends
on the control loop's error handling and recovery policy.

For `stalled_control_loop`, start the server, wait for NORMAL, then select
**Disable** for the battery in the Power tab. The dummy controller delays
that command asynchronously for 18 seconds, after which the control loop
resumes. The web server should remain responsive during the delay.

For `recovering_controller`, open the Power tab to request controller status.
The first ten reads fail and produce CAUTION. Keep the System Health dialog
open and continue observing; after a successful read, the issue clears and
the alarm returns to NORMAL without restarting the server. Status requests
are driven by the UI and control-loop listeners, so recovery timing varies.
