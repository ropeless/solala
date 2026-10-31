DROP TABLE IF EXISTS register CASCADE;
DROP TABLE IF EXISTS solar_forecast CASCADE;
DROP TABLE IF EXISTS measurement CASCADE;


CREATE TABLE measurement
(
    timestamp                       TIMESTAMPTZ PRIMARY KEY, -- expect a record each 5 minutes

    solar_power                     DOUBLE PRECISION,        -- Watts at the timestamp
    grid_power                      DOUBLE PRECISION,        -- Watts at the timestamp
    house_power                     DOUBLE PRECISION,        -- Watts at the timestamp
    battery_power                   DOUBLE PRECISION,        -- Watts at the timestamp
    battery_charge                  DOUBLE PRECISION,        -- Watts at the timestamp

    buy_price                       DOUBLE PRECISION,        -- c/kWh at the timestamp
    feed_in_price                   DOUBLE PRECISION,        -- c/kWh at the timestamp

    accumulated_solar_energy        DOUBLE PRECISION,        -- energy produced since some reference time
    accumulated_grid_energy_import  DOUBLE PRECISION,        -- energy drawn from grid since some reference time
    accumulated_grid_energy_export  DOUBLE PRECISION,        -- energy drawn since some reference time

    battery_mode                    TEXT,
    battery_policy                  TEXT,
    inverter_mode                   TEXT,
    inverter_policy                 TEXT
);

CREATE TABLE solar_forecast
(
    issued_at         TIMESTAMPTZ NOT NULL,
    target_time       TIMESTAMPTZ NOT NULL,
    irradiance_wm2    DOUBLE PRECISION,
    temperature_c     DOUBLE PRECISION,
    predicted_power_w DOUBLE PRECISION,

    PRIMARY KEY (issued_at, target_time)
);

CREATE INDEX solar_forecast_target_idx
    ON solar_forecast (target_time);


CREATE TABLE register
(
    timestamp TIMESTAMPTZ PRIMARY KEY, -- should reference an entry in "measurements" table
    name      TEXT,                    -- name of the register
    value     DOUBLE PRECISION         -- only numeric registers are recorded
)