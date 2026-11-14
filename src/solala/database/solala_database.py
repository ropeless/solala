from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from pydantic import BaseModel

from solala.database.measurement import Measurement

_ENUM_FIELDS: dict[type[BaseModel], list[tuple[str, type[Enum]]]] = {}

type Row = dict[str, Any]


class SolalaDatabase:
    """
    Provide asynchronous access to Solala measurements and register history.

    The instance holds a database connection until it is transferred to its
    owner or released. Measurement model enum fields are stored by member name.
    """
    def __init__(self, connection: AsyncConnection) -> None:
        self.__connection: AsyncConnection | None = connection

    @property
    def _connection(self) -> AsyncConnection:
        connection = self.__connection
        if connection is None:
            raise RuntimeError('database connection has been released')
        return connection

    def _take_connection(self) -> AsyncConnection:
        """
        Transfer ownership of the connection out of this database wrapper.

        Returns:
            The underlying database connection.

        Raises:
            RuntimeError: If the connection has already been transferred.
        """
        connection = self._connection
        self.__connection = None
        return connection

    async def insert_measurement(self, measurement: Measurement) -> None:
        """
        Store a power-system measurement.

        Args:
            measurement: Measurement to insert.
        """
        await self._insert('measurement', measurement)

    async def insert_registers_numeric(
            self,
            timestamp: datetime,
            registers: Mapping[str, int | float],
    ) -> None:
        """
        Insert numeric register values into the database.

        All values share the supplied timestamp. An empty mapping is ignored.

        Args:
            timestamp: Time associated with the register readings.
            registers: Register names mapped to numeric values.
        """
        if not registers:
            return

        params = [
            {'timestamp': timestamp, 'name': name, 'value': value}
            for name, value in registers.items()
        ]
        query = """
            INSERT INTO register_numeric (timestamp, name, value)
            VALUES (%(timestamp)s, %(name)s, %(value)s)
        """
        async with self._connection.transaction():
            async with self._connection.cursor() as cur:
                await cur.executemany(query, params)

    async def insert_registers_text(
            self,
            timestamp: datetime,
            registers: Mapping[str, str],
    ) -> None:
        """
        Insert text register values into the database.

        All values share the supplied timestamp. An empty mapping is ignored.

        Args:
            timestamp: Time associated with the register readings.
            registers: Register names mapped to text values.
        """
        if not registers:
            return

        params = [
            {'timestamp': timestamp, 'name': name, 'value': value}
            for name, value in registers.items()
        ]
        query = """
            INSERT INTO register_text (timestamp, name, value)
            VALUES (%(timestamp)s, %(name)s, %(value)s)
        """
        async with self._connection.transaction():
            async with self._connection.cursor() as cur:
                await cur.executemany(query, params)

    async def get_measurements(
            self,
            day: date,
            include_boundaries: bool = True,
    ) -> Sequence[Measurement]:
        """
        Retrieve measurements for a day in ascending timestamp order.

        Optionally include the nearest measurement before the day and the
        nearest measurement on or after the next day's start, to support
        interpolation at the day boundaries.

        Args:
            day: Date for which measurements are requested.
            include_boundaries: Whether to include the surrounding measurements.

        Returns:
            Measurements in timestamp order, or an empty sequence if none exist.
        """
        day_start = datetime.combine(day, time.min)
        next_day_start = day_start + timedelta(days=1)
        params = {'day_start': day_start, 'next_day_start': next_day_start}

        if include_boundaries:
            query = """
                SELECT * FROM (
                    (
                        SELECT *
                        FROM measurement
                        WHERE timestamp < %(day_start)s
                        ORDER BY timestamp DESC
                        LIMIT 1
                    )
                    UNION ALL
                    (
                        SELECT *
                        FROM measurement
                        WHERE timestamp >= %(day_start)s
                          AND timestamp < %(next_day_start)s
                    )
                    UNION ALL
                    (
                        SELECT *
                        FROM measurement
                        WHERE timestamp >= %(next_day_start)s
                        ORDER BY timestamp ASC
                        LIMIT 1
                    )
                ) AS combined
                ORDER BY timestamp ASC
            """
        else:
            query = """
                SELECT *
                FROM measurement
                WHERE timestamp >= %(day_start)s
                  AND timestamp < %(next_day_start)s
                ORDER BY timestamp ASC
            """

        async with self._connection.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            rows: list[Row] = await cur.fetchall()
            return [_model_from_dict(row, Measurement) for row in rows]

    async def get_latest_measurement(self) -> Measurement | None:
        """
        Retrieve the most recent measurement by timestamp.

        Returns:
            The latest measurement, or None if the database contains none.
        """
        query = """
            SELECT *
            FROM measurement
            ORDER BY timestamp DESC
            LIMIT 1
        """
        async with self._connection.cursor(row_factory=dict_row) as cur:
            await cur.execute(query)
            row: Row | None = await cur.fetchone()
            if row is None:
                return None
            else:
                return _model_from_dict(row, Measurement)

    async def _insert(self, table: str, data: BaseModel) -> None:
        """
        Insert a Pydantic model into a table using its field names as columns.

        Enum fields are stored by member name for later reconstruction.

        Args:
            table: Destination database table.
            data: Model containing the values to insert.
        """
        dumped = data.model_dump()
        # Store enums by member name to match _model_from_dict deserialization
        for field_name, _ in _get_enum_fields(type(data)):
            val = getattr(data, field_name)
            if isinstance(val, Enum):
                dumped[field_name] = val.name

        columns = list(dumped.keys())
        query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
            sql.Identifier(table),
            sql.SQL(', ').join(sql.Identifier(col) for col in columns),
            sql.SQL(', ').join(sql.Placeholder() for _ in columns),
        )
        async with self._connection.cursor() as cur:
            await cur.execute(query, list(dumped.values()))


def _model_from_dict[ModelT: BaseModel](row: Row, model_type: type[ModelT]) -> ModelT:
    """
    Validate a database row as a Pydantic model.

    Convert enum member names back to enum values before validation. The input
    dictionary is modified in place for those fields.

    Args:
        row: Database row keyed by column name.
        model_type: Pydantic model class to construct.

    Returns:
        Validated model instance.
    """
    for field_name, enum_type in _get_enum_fields(model_type):
        raw_val = row.get(field_name)
        if isinstance(raw_val, str):
            row[field_name] = enum_type[raw_val]
    return model_type.model_validate(row)


def _get_enum_fields(model_type: type[BaseModel]) -> list[tuple[str, type[Enum]]]:
    """
    Find enum-typed fields in a Pydantic model, including optional enums.

    Results are cached by model class.

    Args:
        model_type: Pydantic model class to inspect.

    Returns:
        Pairs of field names and enum classes.
    """
    cached = _ENUM_FIELDS.get(model_type)
    if cached is not None:
        return cached

    found: list[tuple[str, type[Enum]]] = []
    for field_name, field in model_type.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            found.append((field_name, annotation))
        elif get_origin(annotation) in (Union, UnionType):
            for arg in get_args(annotation):
                if isinstance(arg, type) and issubclass(arg, Enum):
                    found.append((field_name, arg))
                    break

    _ENUM_FIELDS[model_type] = found
    return found
