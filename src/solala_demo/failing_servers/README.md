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
- `command_failure_keep_alive`: persistent inverter disable timeout; exercises repeated keep-alive WARNING
- `command_failure_one_shot`: persistent battery disable timeout; exercises one-shot WARNING and recovery
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

For `intermittent_solar_failure`, the forecast cache is deliberately shortened
(5 seconds fresh, 20 seconds maximum age) to make retries observable without
waiting an hour. Open the Solar tab and watch the forecast and server log for
several refresh cycles. Failed refreshes may continue serving a cached forecast;
a forecast failure does **not** itself create a master-alarm CAUTION issue.
The alarm should remain NORMAL unless another health problem occurs. This
scenario uses random 50% failures, so individual outcomes are not guaranteed.
These cache durations apply only to this demo process.

For `command_failure_one_shot`, select **Disable** for the battery. The
command fails once, the reported mode becomes UNKNOWN, and WARNING persists
without automatic retries. Select a different battery mode to verify that a
successful command restores the reported mode and clears the warning.
