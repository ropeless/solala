from datetime import date, datetime
from enum import Enum
from typing import Optional, TypeVar, Dict, List, Tuple, Sequence, Any, TypeAlias, Mapping

from psycopg import sql, AsyncConnection, AsyncCursor
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from solala.database.measurement import Measurement
from solala.registers import RegisterValue

Row: TypeAlias = Tuple[Any, ...]
Cursor: TypeAlias = AsyncCursor[Row]


class SolalaDatabase:

    def __init__(self, connection: AsyncConnection):
        self._connection: AsyncConnection = connection

    async def insert_measurement(self, measurement: Measurement) -> None:
        await self._insert('measurement', measurement)

    async def insert_registers(
            self, timestamp: datetime,
            registers: Mapping[str, int|float]
    ) -> None:
        """
        Insert register values into the database
        """
        params = [
            {"timestamp": timestamp, "name": name, "value": value}
            for name, value in registers.items()
        ]
        if len(params) == 0:
            return

        query = """
                INSERT INTO registers (timestamp, name, value)
                VALUES (%(timestamp)s, %(name)s, %(value)s) \
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
        measurements of the previous and nest days to support interpolation.

        Args:
            day: The day of interest; measurements of this day are returned.
            include_boundaries: Whether to include boundary measurements from the previous and next days.

        Returns:
            A sequence of measurements for the given day, in order of increasing time.
        """
        if include_boundaries:
            query = """
            (
                SELECT *
                FROM measurement
                WHERE date (timestamp) < %(day)s
                ORDER BY timestamp DESC
                LIMIT 1
            )
            UNION ALL
            (
                SELECT *
                FROM measurement
                WHERE date (timestamp) = %(day)s
                ORDER BY timestamp ASC
            )
            UNION ALL
            (
                SELECT *
                FROM measurement
                WHERE date (timestamp) > %(day)s
                ORDER BY timestamp ASC
                LIMIT 1
            )
            """
        else:
            query = """
                    SELECT *
                    FROM measurement
                    WHERE date (timestamp) = %(day)s
                    ORDER BY timestamp ASC
                    """
        result: Cursor = await self._connection.execute(query, {'day': day})
        rows: List[Row] = await result.fetchall()
        return [
            _model_from_row(row, result, Measurement)
            for row in rows
        ]

    async def get_latest_measurement(self) -> Optional[Measurement]:
        """
        Get the latest measurement (if there is one).
        """
        result = await self._connection.execute(
            """
            SELECT *
            FROM measurement
            ORDER BY timestamp DESC
                LIMIT 1
            """
        )
        row: Optional[Row] = await result.fetchone()
        return _model_from_row(row, result, Measurement) if row is not None else None

    async def _insert(self, table: str, data: BaseModel) -> None:
        data = data.model_dump()
        columns = list(data.keys())
        query = sql.SQL(
            'INSERT INTO {} ({}) VALUES ({})'
        ).format(
            sql.Identifier(table),
            sql.SQL(', ').join(sql.Identifier(column) for column in columns),
            sql.SQL(', ').join(sql.Placeholder() for _ in columns),
        )
        await self._connection.execute(query, list(data.values()))


_ModelType = TypeVar('_ModelType', covariant=True, bound=BaseModel)


def _model_from_row(row: Row, cursor: Cursor, model_type: type[_ModelType]) -> _ModelType:
    """
    Convert a database row to a Pydantic object of type `model_type`.
    Correctly deals with enum fields (stored using member names).
    """
    columns_description = cursor.description
    if columns_description is None:
        raise ValueError('cursor has no result-set description')

    columns = [column.name for column in columns_description]
    row_as_dict = dict(zip(columns, row, strict=True))

    for field_name, enum_type in _get_enum_fields(model_type):
        row_as_dict[field_name] = enum_type[row_as_dict[field_name]]
    return model_type.model_validate(row_as_dict)


# -------------------------------------------------------------------------
#   Keep track of enum fields for each Pydantic model type encountered.
# -------------------------------------------------------------------------

_ENUM_FIELDS: Dict[type, List[Tuple[str, type[Enum]]]] = {}


def _get_enum_fields(model_type: type[_ModelType]) -> List[Tuple[str, type[Enum]]]:
    """
    Get a list of all enum fields in the given Pydantic type.

    Warning: This does not deal with `Optional` types.
    """
    got = _ENUM_FIELDS.get(model_type)
    if got is not None:
        return got
    got: List[Tuple[str, type[Enum]]] = []

    model_fields: Dict[str, FieldInfo] = model_type.__pydantic_fields__
    for field_name, field in model_fields.items():
        if (
                isinstance(field.annotation, type)
                and issubclass(field.annotation, Enum)
        ):
            got.append((field_name, field.annotation))
    _ENUM_FIELDS[model_type] = got
    return got
