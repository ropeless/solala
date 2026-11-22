Control Modes and Policies
==========================

Solala distinguishes between a **mode**, which describes the operating state
requested for a device, and a **policy**, which determines whether that mode
is selected manually or adjusted automatically.

Battery and inverter modes and policies are configured independently:

- **Battery modes:** Enable (normal charging and discharging), Disable,
  Force Charge, Force Discharge, Charge Only and Discharge Only.
- **Inverter modes:** Enable (normal operation), Disable (stop solar power
  production), Fixed Limit (cap inverter output at a configured percentage
  of rated power) and Zero Export (minimise power exported to the grid).
- **Manual policy:** Solala uses the mode selected by the user.
- **Automatic battery policy — Cheap Charge:** Switches to Force Charge
  when the electricity purchase price is sufficiently low, and stops forced
  charging when the price rises above a separate threshold.
- **Automatic inverter policy — Negative Feed-in Zero Export:** Selects
  Zero Export when the feed-in price falls below the configured threshold,
  and re-enables normal operation when it rises above a separate threshold.

The Power tab's **FIXED LIMIT** button selects the manual Fixed Limit mode.
Server settings supply the percentage. Solala reapplies the cap on each
control-loop iteration while the mode is active. See [Getting Started](getting_started.md)
for configuration.

The separate start/stop and disable/enable price thresholds allow policies
to avoid repeatedly switching modes when prices fluctuate near a boundary.
For example, a negative feed-in tariff can trigger Zero Export without
requiring the user to disable the inverter manually.

When switching from **Fixed Limit** to **Negative Feed-in Zero Export**, Solala
keeps applying the fixed cap until it has a finite, non-estimated feed-in price.
It then starts in Enable if the price is above the enable threshold, or Zero
Export otherwise. Subsequent prices use the normal hysteresis rules.

The mode, policy and thresholds are represented together by `ControlMode`
in `src/solala/control_loop/modes_and_policies.py`. The control loop
evaluates these settings and sends commands through the `PowerController`
interface. Actual device behaviour depends on the inverter and battery
capabilities and configuration.
