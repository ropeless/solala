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
        role: Database user name.
        password: Database password.
        host: Database server host.
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
            role: Database user name.
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
        self._connection_info: JSONDict = {
            'role': role,
            'host': host,
            'port': port,
            'database_name': database_name,
        }

    def get_connection_info(self) -> JSONDict:
        """
        Return connection settings without the password.

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
        Borrow a database wrapper from the pool for a managed scope.

        On normal exit, commit or roll back according to `commit_on_close`.
        The pooled connection is returned when the context exits.

        Args:
            commit_on_close: Commit on normal exit if True; otherwise roll back.
            timeout: Maximum time to wait for a connection, in seconds.

        Yields:
            Database wrapper backed by a pooled connection.
        """
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
