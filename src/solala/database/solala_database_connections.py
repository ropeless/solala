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


class DatabaseLease:
    """
    Reserve a database pool lifetime while a caller uses it.

    The reservation is created synchronously and released by the context.
    """

    def __init__(self, owner: SolalaDatabaseConnections) -> None:
        self._owner = owner
        self._entered = False
        self._released = False

    async def __aenter__(self) -> DatabaseLease:
        if self._entered or self._released:
            raise RuntimeError('database lease is not available')
        self._entered = True
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc_value: BaseException | None,
                        traceback: TracebackType | None) -> None:
        self.release()

    def release(self) -> None:
        """
        Release this lease exactly once.
        """
        if not self._released:
            self._released = True
            self._owner._release_lease()

    @asynccontextmanager
    async def solala_database(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> AsyncIterator[SolalaDatabase]:
        """
        Borrow a connection under this lease.
        """
        if not self._entered or self._released:
            raise RuntimeError('database lease is not active')
        async with self._owner._borrow_database(commit_on_close, timeout) as db:
            yield db


class SolalaDatabaseConnections:
    """
    Manage a pool of asynchronous connections to the Solala database.

    Use the pool as an asynchronous context manager to open and close it.
    Individual database wrappers can be borrowed with `solala_database()`
    or with the paired `get_db()` and `put_db()` methods.

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
        self._active_leases = 0
        self._closing = False
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

    def reserve(self) -> DatabaseLease:
        """
        Reserve the pool before asynchronous connection acquisition.
        """
        if self._closing:
            raise ConnectionError('Database pool is closing')
        self._active_leases += 1
        self._drained.clear()
        return DatabaseLease(self)

    def _release_lease(self) -> None:
        """
        Notify a closing pool when the last borrower finishes.
        """
        self._active_leases -= 1
        if self._active_leases == 0:
            self._drained.set()

    @asynccontextmanager
    async def solala_database(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> AsyncIterator[SolalaDatabase]:
        """
        Borrow a connection using a managed lifetime reservation.
        """
        lease = self.reserve()
        try:
            async with lease:
                async with lease.solala_database(commit_on_close, timeout) as db:
                    yield db
        finally:
            lease.release()

    @asynccontextmanager
    async def _borrow_database(
            self,
            commit_on_close: bool,
            timeout: float | None,
    ) -> AsyncIterator[SolalaDatabase]:
        """
        Manage a pooled connection under an existing lease.
        """
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

    async def get_db(self, timeout: float | None = None) -> SolalaDatabase:
        """
        Borrow a database wrapper that must later be returned with `put_db()`.

        Args:
            timeout: Maximum time to wait for a connection, in seconds.

        Returns:
            Database wrapper backed by a pooled connection.
        """
        conn: AsyncConnection = await self._pool.getconn(timeout=timeout)
        return SolalaDatabase(conn)

    async def put_db(self, db: SolalaDatabase, commit_on_close: bool = True) -> None:
        """
        Finalise a borrowed database connection and return it to the pool.

        Args:
            db: Database wrapper previously obtained with `get_db()`.
            commit_on_close: Commit changes if True; otherwise roll back.
        """
        # noinspection PyProtectedMember
        conn: AsyncConnection = db._take_connection()
        try:
            if commit_on_close:
                await conn.commit()
            else:
                await conn.rollback()
        finally:
            await self._pool.putconn(conn)

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
            self._closing = True
            await self._drained.wait()
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
