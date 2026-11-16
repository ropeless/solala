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
    Reserve a pool lifetime across asynchronous database operations.

    A lease is acquired synchronously before the caller releases its
    connection-state lock. It must be entered exactly once.
    """

    def __init__(self, owner: 'SolalaDatabaseConnections') -> None:
        self._owner = owner
        self._entered = False
        self._released = False

    async def __aenter__(self) -> 'DatabaseLease':
        if self._entered:
            raise RuntimeError('database lease already entered')
        self._entered = True
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc_value: BaseException | None,
                        traceback: TracebackType | None) -> None:
        self.release()

    def release(self) -> None:
        """Release the reservation, including when acquisition is cancelled."""
        if self._released:
            return
        self._released = True
        self._owner._release_lease()

    def reserve(self) -> DatabaseLease:
        """
        Reserve the pool lifetime before any asynchronous acquisition.

        The caller must enter and release the returned lease. This method is
        synchronous so it can be called under the connections-state lock.
        """
        if self._closing:
            raise ConnectionError('Database pool is closing')
        self._active_leases += 1
        self._drained.clear()
        return DatabaseLease(self)

    def _release_lease(self) -> None:
        self._active_leases -= 1
        if self._active_leases == 0:
            self._drained.set()

    @asynccontextmanager
    async def solala_database(
            self,
            commit_on_close: bool = True,
            timeout: float | None = None,
    ) -> AsyncIterator[SolalaDatabase]:
        """Borrow a database wrapper with its own lifetime reservation."""
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
        """Manage a borrowed connection without creating another lease."""
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
        Finalize a borrowed database connection and return it to the pool.

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
