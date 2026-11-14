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
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection: AsyncConnection = connection

    async def insert_measurement(self, measurement: Measurement) -> None:
        await self._insert('measurement', measurement)

    async def insert_registers_numeric(
            self,
            timestamp: datetime,
            registers: Mapping[str, int | float],
    ) -> None:
        """
        Insert numeric register values into the database.
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
        Get the measurements for a given day. Optionally include the boundary
        measurements of the previous and next days to support interpolation.
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
        Get the latest measurement (if there is one).
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
    Convert a database row dictionary to a Pydantic object of type `model_type`.
    """
    for field_name, enum_type in _get_enum_fields(model_type):
        raw_val = row.get(field_name)
        if isinstance(raw_val, str):
            row[field_name] = enum_type[raw_val]
    return model_type.model_validate(row)


def _get_enum_fields(model_type: type[BaseModel]) -> list[tuple[str, type[Enum]]]:
    """
    Get all Enum (including Optional[Enum]) fields in the given Pydantic model.
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
