from __future__ import annotations

import asyncio
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
    """
    Build a PostgreSQL connection URI with encoded credentials.

    Args:
        role: Database username.
        password: Database user password.
        host: Database server hostname or IP address.
        port: Database server port.
        database_name: Database name, or None to omit it from the URI.

    Returns:
        PostgreSQL connection URI.
    """
    safe_role = quote_plus(role)
    safe_password = quote_plus(password)
    db_path = f'/{database_name}' if database_name else ''
    return f'postgresql://{safe_role}:{safe_password}@{host}:{port}{db_path}'


class SolalaDatabaseConnections:
    """
    Manage a pool of asynchronous connections to the Solala database.

    Use the pool as an asynchronous context manager to open and close it.
    Individual database wrappers are borrowed with `solala_database()`.

    Example:
        async with SolalaDatabaseConnections(...) as pool:
            async with pool.solala_database() as db:
                # Use the database.
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
        """
        Configure the connection pool without opening it.

        Args:
            role: Database username.
            password: Database password.
            host: Database server host.
            port: Database server port.
            database_name: Database name.
            min_pool_size: Minimum number of pooled connections.
            max_pool_size: Maximum number of pooled connections.
        """
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
        self._active_requests = 0
        self._closing = False
        self._closed = False
        self._drained = asyncio.Event()
        self._drained.set()
        self._close_lock = asyncio.Lock()
        self._connection_info: JSONDict = {
            'role': role,
            'host': host,
            'port': port,
            'database_name': database_name,
        }

    def get_connection_info(self) -> JSONDict:
        """
        Return connection settings (without the password).

        Returns:
            Connection role, host, port, and database name.
        """
        return self._connection_info

    @asynccontextmanager
    async def solala_database(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> AsyncIterator[SolalaDatabase]:
        """
        Borrow a database wrapper and protect the pool until it is returned.

        Pending acquisitions count as active requests, so shutdown waits for
        them as well as for connections already in use.
        """
        if self._closing:
            raise ConnectionError('Database pool is closing')
        self._active_requests += 1
        self._drained.clear()
        try:
            await self.open(wait=False)
            async with self._pool.connection(timeout=timeout) as conn:
                db = SolalaDatabase(conn)
                try:
                    yield db
                    if commit_on_close:
                        await conn.commit()
                    else:
                        await conn.rollback()
                finally:
                    # noinspection PyProtectedMember
                    db._take_connection()
        finally:
            self._active_requests -= 1
            if self._active_requests == 0:
                self._drained.set()

    def get_stats(self) -> dict[str, int]:
        """
        Return the underlying connection pool's statistics.

        Returns:
            Pool statistics keyed by metric name.
        """
        return self._pool.get_stats()

    async def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        """
        Open the connection pool.

        Args:
            wait: Whether to wait for the minimum pool size to be ready.
            timeout: Maximum wait time in seconds when `wait` is True.
        """
        await self._pool.open(wait=wait, timeout=timeout)

    async def close(self) -> None:
        """
        Close the connection pool and release its connections.
        """
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            await self._drained.wait()
            await self._pool.close()
            self._closed = True

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
