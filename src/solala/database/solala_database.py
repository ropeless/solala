from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from typing import Optional, TypeVar, Dict, List, Tuple, AsyncIterator

import psycopg
from psycopg import sql, AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from solala.constants import DEFAULT_DB_HOST, DEFAULT_DB_PORT, DEFAULT_DB_NAME
from solala.database.measurement import Measurement
from solala.utils.json import JSONDict


class SolalaDatabase:

    def __init__(self, connection: AsyncConnection):
        self._connection: AsyncConnection = connection

    async def insert_measurement(self, measurement: Measurement) -> None:
        await self._insert('measurement', measurement)

    async def get_latest_measurement(self) -> Optional[Measurement]:
        result = await self._connection.execute(
            """
            SELECT *
            FROM measurement
            ORDER BY timestamp DESC
                LIMIT 1
            """
        )
        row: Optional[dict] = await result.fetchone()
        return _model_from_row(row, Measurement) if row is not None else None

    async def get_measurement(self, timestamp: datetime) -> Optional[Measurement]:
        result = await self._connection.execute(
            """
            SELECT *
            FROM measurement
            WHERE timestamp = %s
            """,
            (timestamp,),
        )
        row: Optional[dict] = await result.fetchone()
        return _model_from_row(row, Measurement) if row is not None else None

    async def _insert(self, table: str, data: BaseModel):
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


@asynccontextmanager
async def solala_database(
        role: str,
        password: str,
        host: str = DEFAULT_DB_HOST,
        port: int = DEFAULT_DB_PORT,
        database_name: str = DEFAULT_DB_NAME,
        commit_on_close: bool = True,
) -> AsyncIterator[SolalaDatabase]:
    """
    Single solala database connection.

    Args:
        role: database connection role (aka, username).
        password: database connection password.
        host: database host.
        port: database port.
        database_name: database name.
        commit_on_close: whether to commit changes on close or not.
    """
    connection_string: str = make_connection_string(
        role=role,
        password=password,
        host=host,
        port=port,
        database_name=database_name,
    )
    async with await psycopg.AsyncConnection.connect(
            conninfo=connection_string,
            row_factory=dict_row,
    ) as conn:
        yield SolalaDatabase(conn)
        if commit_on_close:
            await conn.commit()


class SolalaDatabaseConnections:
    """
    Manages a pool of connections to the Solala database.

    Example usage:

    async with SolalaDatabaseConnections(...) as pool:
        async with pool.solala_database() as db:
            # use the database
    """

    def __init__(
            self,
            role: str,
            password: str,
            host: str = DEFAULT_DB_HOST,
            port: int = DEFAULT_DB_PORT,
            database_name: str = DEFAULT_DB_NAME,
    ):
        connection_string: str = make_connection_string(
            role=role,
            password=password,
            host=host,
            port=port,
            database_name=database_name,
        )
        self._pool = AsyncConnectionPool(
            conninfo=connection_string,
            min_size=1,
            max_size=5,
            kwargs={'row_factory': dict_row},
            open=False,
        )
        self._pool_open: bool = False
        self._connection_status: JSONDict = {
            'role': role,
            'host': host,
            'port': port,
            'database_name': database_name,
        }

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

    @asynccontextmanager
    async def solala_database(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> AsyncIterator[SolalaDatabase]:
        """

        Args:
            commit_on_close: whether to commit changes on close or not.
            timeout: connection timeout.

        Returns:
            a SolalaDatabase instance.
        """
        if not self._pool_open:
            await self._pool.open()
            self._pool_open = True
        async with self._pool.connection(timeout=timeout) as conn:
            yield SolalaDatabase(conn)
            if commit_on_close:
                await conn.commit()

    async def get_db(self, timeout: float | None = None) -> SolalaDatabase:
        if not self._pool_open:
            await self._pool.open()
            self._pool_open = True
        conn: AsyncConnection = await self._pool.getconn(timeout=timeout)
        return SolalaDatabase(conn)

    async def put_db(self, db: SolalaDatabase, commit_on_close: bool = True) -> None:
        # noinspection PyProtectedMember
        conn: AsyncConnection = db._connection
        if commit_on_close:
            await conn.commit()
        # noinspection PyTypeChecker
        db._connection = None
        await self._pool.putconn(conn)

    async def open(self) -> None:
        if not self._pool_open:
            await self._pool.open()
            self._pool_open = True

    async def close(self) -> None:
        if self._pool_open:
            await self._pool.close()
            self._pool_open = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


_ModelType = TypeVar('_ModelType', covariant=True, bound=BaseModel)


def _model_from_row(row: Dict, model_type: type[_ModelType]) -> _ModelType:
    """
    Convert a database row to a Pydantic object of type `model_type`.
    Correctly deals with enum fields (stored using member names).
    """
    for field_name, enum_type in _get_enum_fields(model_type):
        row[field_name] = enum_type[row[field_name]]
    return model_type.model_validate(row)


def make_connection_string(
        role: str,
        password: str,
        host: str,
        port: int,
        database_name: str,
) -> str:
    return f'postgresql://{role}:{password}@{host}:{port}/{database_name}'


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
