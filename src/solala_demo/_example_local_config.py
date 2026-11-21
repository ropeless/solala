# This is an example local configuration file. It defines
# environment variables can can be defined in the OS environment,
# a `local_config.py` module or a mixture thereof.
# See `solala.utils.local_config_help` for more details.

APP_NAME_POSTFIX = ' ***DEMO***'

# ============================== Delegates

MASTER_INVERTER_ADDR = '192.168.0.200'
SLAVE_INVERTER_ADDR = '192.168.0.201'

AMBER_API_TOKEN = 'psk_k56thisisnotarealapitokenlm5t0adf0f'
NMI = '4109999999'

# Open-Metio config
LATITUDE = -33.72
LONGITUDE = 151.08
PANEL_ORIENTATION = 0
PANEL_TILT = 30
PANEL_CAPACITY = 9360
PANEL_TEMPERATURE_COEFFICIENT = -0.0038
INVERTER_LIMIT = 8000
INVERTER_EFFICIENCY = 0.976

# ============================== Consumer Devices

# Tesla Wall Connector
TESLA_WALL_CONNECTOR_ADDR = '192.168.0.202'

# Tuya device via Tuya cloud
POWER_POINT_DEVICE = 'kjhasgdfkjhgaskdjhfgkashdgf'
POWER_POINT_ACCESS_ID = 'jfkaskdjfh87193456ka8g'
POWER_POINT_ACCESS_SECRET = 'aflsknotarealsecretdsafjpa127859'

# Tuya device via LAN
TUYA_LOCAL_HOST = '192.168.0.50'
TUYA_LOCAL_DEVICE_ID = '8943590223534598089345'
TUYA_LOCAL_KEY = '90klm8*(OPnl)*('
TUYA_LOCAL_VERSION = 3.5

# for Tapo model P110M via LAN using kasa
TAPO_HOST = '192.168.0.51'
TAPO_USERNAME = 'a_person@devnull.com'
TAPO_PASSWORD = 'rifo;jajfoie0rtj;as'

# for Tapo model P110M via a local Mater server
MATTER_SERVER_HOST = '192.168.0.203'
MATTER_SERVER_PORT = 5580
MATTER_PAIRING_CODE = '098123401-2893470128-93740981'
MATTER_DEVICE_IDS: dict[int, str] = {1: 'plug_1'}

# ============================== End of Delegates


SERVER_HOST = 'localhost'
SERVER_PORT = 8080
SOLALA_STORAGE_SECRET = 'some-large-random-string'  # e.g. use `openssl rand -hex 32` to generate one

OUT = '/users/demo_user/output'
HISTORY_FILE = OUT + '/history.csv'
SETTINGS_PATH = OUT + '/settings.json'
DUMMY_SETTINGS_PATH = OUT + '/settings_dummy.json'

DATABASE_ADMIN_PASSWORD = 'YOUR_PASSWORD'
DATABASE_APP_PASSWORD = 'YOUR_PASSWORD'
DATABASE_HOST = 'localhost'
DATABASE_PORT = 5432
DATABASE_ADMIN_ROLE = 'postgres'
DATABASE_APP_ROLE = 'solala'
DATABASE_NAME = 'solala'
DATABASE_WRITE = False

FORCE_SETTINGS: bool = False
DEMO_LOG_FORMAT: str = '%(asctime)s %(levelname)s: %(name)s %(message)s'
APP_LOG_LEVEL = 'INFO'
