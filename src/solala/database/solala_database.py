from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from typing import Optional, TypeVar, Dict, List, Tuple, Iterator

from psycopg import sql, Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy


class Measurement(BaseModel):
    timestamp: datetime

    solar_power: float
    grid_power: float
    house_power: float
    battery_power: float
    battery_charge: float

    buy_price: float
    feed_in_price: float

    accumulated_solar_energy: float
    accumulated_grid_energy_draw: float
    accumulated_grid_energy_feed_in: float

    battery_mode: BatteryMode
    battery_policy: BatteryPolicy
    inverter_mode: InverterMode
    inverter_policy: InverterPolicy


class SolalaDatabase:

    def __init__(self, connection: Connection):
        self._connection = connection

    def insert_measurement(self, measurement: Measurement) -> None:
        self._insert('measurement', measurement)

    def get_latest_measurement(self) -> Optional[Measurement]:
        row: Optional[dict] = self._connection.execute(
            """
            SELECT *
            FROM measurement
            ORDER BY timestamp DESC
                LIMIT 1
            """
        ).fetchone()
        return _model_from_row(row, Measurement) if row is not None else None

    def get_measurement(self, timestamp: datetime) -> Optional[Measurement]:
        row: Optional[dict] = self._connection.execute(
            """
            SELECT *
            FROM measurement
            WHERE timestamp = %s
            """,
            (timestamp,),
        ).fetchone()
        return _model_from_row(row, Measurement) if row is not None else None

    def _insert(self, table: str, data: BaseModel):
        data = data.model_dump()
        columns = list(data.keys())
        query = sql.SQL(
            'INSERT INTO {} ({}) VALUES ({})'
        ).format(
            sql.Identifier(table),
            sql.SQL(', ').join(sql.Identifier(column) for column in columns),
            sql.SQL(', ').join(sql.Placeholder() for _ in columns),
        )
        self._connection.execute(query, list(data.values()))

    def commit(self) -> None:
        self._connection.commit()


class SolalaConnections:
    """
    Manages a pool of connections to the Solala database.
    """

    def __init__(self, connection_string: str):
        self._pool = ConnectionPool(
            conninfo=connection_string,
            min_size=1,
            max_size=5,
            kwargs={'row_factory': dict_row},
            open=True,
        )

    @contextmanager
    def solala_data(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> Iterator[SolalaDatabase]:
        with self._pool.connection(timeout=timeout) as conn:
            solala_data = SolalaDatabase(conn)
            yield solala_data
            if commit_on_close:
                solala_data.commit()

    def close(self):
        self._pool.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return exc_type is None


_ModelType = TypeVar('_ModelType', covariant=True, bound=BaseModel)


def _model_from_row(row: Dict, model_type: type[_ModelType]) -> _ModelType:
    """
    Convert a database row to a Pydantic object of type `model_type`.
    Correctly deals with enum fields (stored using member names).
    """
    for field_name, enum_type in _get_enum_fields(model_type):
        row[field_name] = enum_type[row[field_name]]
    return model_type.model_validate(row)


# -------------------------------------------------------------------------
#   Keep track of enum fields for each Pydantic model type encountered.
# -------------------------------------------------------------------------

_ENUM_FIELDS: Dict[type, List[Tuple[str, type[Enum]]]] = {}


def _get_enum_fields(model_type: type[_ModelType]) -> List[Tuple[str, type[Enum]]]:
    got = _ENUM_FIELDS.get(model_type)
    if got is not None:
        return got
    got: List[Tuple[str, type[Enum]]] = []
    for field_name, field in model_type.model_fields.items():
        if (
                isinstance(field.annotation, type)
                and issubclass(field.annotation, Enum)
        ):
            got.append((field_name, field.annotation))
    _ENUM_FIELDS[model_type] = got
    return got
