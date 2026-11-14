from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self
from urllib.parse import quote_plus

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from solala.constants import DEFAULT_DB_HOST, DEFAULT_DB_NAME, DEFAULT_DB_PORT
from solala.database.solala_database import SolalaDatabase
from solala.utils.json_extras import JSONDict


def make_connection_string(
        role: str,
        password: str,
        host: str,
        port: int,
        database_name: str | None = None,
) -> str:
    safe_role = quote_plus(role)
    safe_password = quote_plus(password)
    db_path = f'/{database_name}' if database_name else ''
    return f'postgresql://{safe_role}:{safe_password}@{host}:{port}{db_path}'


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
            min_pool_size: int = 2,
            max_pool_size: int = 8,
    ) -> None:
        connection_string = make_connection_string(
            role=role,
            password=password,
            host=host,
            port=port,
            database_name=database_name,
        )
        self._pool = AsyncConnectionPool(
            conninfo=connection_string,
            min_size=min_pool_size,
            max_size=max_pool_size,
            open=False,
        )
        self._connection_info: JSONDict = {
            'role': role,
            'host': host,
            'port': port,
            'database_name': database_name,
        }

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    @asynccontextmanager
    async def solala_database(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> AsyncIterator[SolalaDatabase]:
        """
        Yields a SolalaDatabase instance backed by a pooled connection.

        Args:
            commit_on_close: Whether to commit changes on exit (rolls back if False).
            timeout: Connection acquisition timeout in seconds.

        Returns:
            A SolalaDatabase instance.
        """
        async with self._pool.connection(timeout=timeout) as conn:
            yield SolalaDatabase(conn)
            if commit_on_close:
                await conn.commit()
            else:
                await conn.rollback()

    async def get_db(self, timeout: float | None = None) -> SolalaDatabase:
        conn: AsyncConnection = await self._pool.getconn(timeout=timeout)
        return SolalaDatabase(conn)

    async def put_db(self, db: SolalaDatabase, commit_on_close: bool = True) -> None:
        # noinspection PyProtectedMember
        conn: AsyncConnection = db._connection
        # noinspection PyTypeChecker
        db._connection = None
        try:
            if commit_on_close:
                await conn.commit()
            else:
                await conn.rollback()
        finally:
            await self._pool.putconn(conn)

    def get_stats(self) -> dict[str, int]:
        return self._pool.get_stats()

    async def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        await self._pool.open(wait=wait, timeout=timeout)

    async def close(self) -> None:
        await self._pool.close()

    async def __aenter__(self) -> Self:
        await self.open(wait=True)
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
    ) -> None:
        await self.close()
