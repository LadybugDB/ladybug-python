from __future__ import annotations

import asyncio
import threading
import warnings
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from .connection import Connection
from .prepared_statement import PreparedStatement

if TYPE_CHECKING:
    import sys
    from types import TracebackType

    from .database import Database
    from .query_result import QueryResult

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


class AsyncConnection:
    """AsyncConnection enables asynchronous execution of queries with a pool of connections and threads."""

    def __init__(
        self,
        database: Database,
        max_concurrent_queries: int = 4,
        max_threads_per_query: int = 0,
    ) -> None:
        """
        Initialise the async connection.

        Parameters
        ----------
        database : Database
            Database to connect to.

        max_concurrent_queries : int
            Maximum number of concurrent queries to execute. This corresponds to the
            number of connections and thread pool size. Default is 4.

        max_threads_per_query : int
            Controls the maximum number of threads per connection that can be used
            to execute one query. Default is 0, which means no limit.
        """
        self.database = database
        self.connections = [Connection(database) for _ in range(max_concurrent_queries)]
        self.connections_counter = [0 for _ in range(max_concurrent_queries)]
        self.lock = threading.Lock()
        # Calls on one connection run one at a time (the engine serializes them
        # anyway), so the call holding a connection's lock is the one an
        # interrupt would hit. Queries run directly on a connection obtained
        # from acquire_connection() are not tracked.
        self._connection_locks: weakref.WeakKeyDictionary[
            Connection, threading.Lock
        ] = weakref.WeakKeyDictionary()
        self._running: dict[Connection, _Call] = {}

        for conn in self.connections:
            conn.init_connection()
            conn.set_max_threads_for_exec(max_threads_per_query)

        self.executor = ThreadPoolExecutor(max_workers=max_concurrent_queries)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def __get_connection_with_least_queries(self) -> tuple[Connection, int]:
        with self.lock:
            conn_index = self.connections_counter.index(min(self.connections_counter))
            self.connections_counter[conn_index] += 1
        return self.connections[conn_index], conn_index

    def __decrement_connection_counter(self, conn_index: int) -> None:
        """Decrement the query counter for a connection."""
        with self.lock:
            self.connections_counter[conn_index] -= 1
            if self.connections_counter[conn_index] < 0:
                self.connections_counter[conn_index] = 0

    def acquire_connection(self) -> Connection:
        """
        Acquire a connection from the connection pool for temporary synchronous
        calls. If the connection pool is oversubscribed, the method will return
        the connection with the least number of queued queries. It is required
        to release the connection by calling `release_connection` after the
        connection is no longer needed.

        Returns
        -------
        Connection
            A connection object.
        """
        conn, _ = self.__get_connection_with_least_queries()
        return conn

    def release_connection(self, conn: Connection) -> None:
        """
        Release a connection acquired by `acquire_connection` back to the
        connection pool. Calling this method is required when the connection is
        no longer needed.

        Parameters
        ----------
        conn : Connection
            Connection object to release.


        """
        conn_index = self.__index_of(conn)
        if conn_index is not None:
            self.__decrement_connection_counter(conn_index)

    def set_query_timeout(self, timeout_in_ms: int) -> None:
        """
        Set the query timeout value in ms for executing queries.

        Parameters
        ----------
        timeout_in_ms : int
            query timeout value in ms for executing queries.

        """
        for conn in self.connections:
            conn.set_query_timeout(timeout_in_ms)

    async def execute(
        self, query: str | PreparedStatement, parameters: dict[str, Any] | None = None
    ) -> QueryResult | list[QueryResult]:
        """
        Execute a query asynchronously.

        Parameters
        ----------
        query : str | PreparedStatement
            A prepared statement or a query string.
            If a query string is given, a prepared statement will be created
            automatically.

        parameters : dict[str, Any]
            Parameters for the query.

        Returns
        -------
        QueryResult
            Query result.

        Raises
        ------
        asyncio.CancelledError
            If the awaiting task is cancelled. A running query is interrupted; a
            query still waiting for a free connection is not started.

        """
        if isinstance(query, PreparedStatement):
            conn = query._connection
            conn_index = self.__index_of(conn)
            if conn_index is not None:
                with self.lock:
                    self.connections_counter[conn_index] += 1
        else:
            conn, conn_index = self.__get_connection_with_least_queries()
        return await self.__submit(conn, conn_index, conn.execute, query, parameters)

    async def _prepare(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> PreparedStatement:
        """
        The only parameters supported during prepare are dataframes.
        Any remaining parameters will be ignored and should be passed to execute().
        """  # noqa: D401
        conn, conn_index = self.__get_connection_with_least_queries()
        return await self.__submit(conn, conn_index, conn._prepare, query, parameters)

    def __index_of(self, conn: Connection) -> int | None:
        for i, existing_conn in enumerate(self.connections):
            if existing_conn is conn:
                return i
        return None

    async def __submit(
        self, conn: Connection, conn_index: int | None, fn: Any, *args: Any
    ) -> Any:
        call = _Call()
        try:
            future = self.executor.submit(self.__run, conn, call, fn, *args)
        except RuntimeError:
            if conn_index is not None:
                self.__decrement_connection_counter(conn_index)
            raise
        if conn_index is not None:
            # Release the slot when the work has actually finished (or was
            # cancelled before it started), not when the awaiting task exits.
            future.add_done_callback(
                lambda _: self.__decrement_connection_counter(conn_index)
            )
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            self.__cancel(conn, call)
            raise

    def __run(self, conn: Connection, call: _Call, fn: Any, *args: Any) -> Any:
        with self.lock:
            connection_lock = self._connection_locks.setdefault(conn, threading.Lock())
        with connection_lock:
            with self.lock:
                if call.cancelled:
                    return None
                self._running[conn] = call
            try:
                return fn(*args)
            finally:
                with self.lock:
                    del self._running[conn]

    def __cancel(self, conn: Connection, call: _Call) -> None:
        # Interrupting acts on whatever the connection is running, so only
        # interrupt while this call is the one running. A call still waiting
        # for its connection is skipped when its turn comes.
        with self.lock:
            call.cancelled = True
            running = self._running.get(conn) is call
            if running:
                conn.interrupt()
        if running:
            # An interrupt that arrives while the query is still compiling is
            # cleared when execution starts, so repeat it until the call returns.
            asyncio.get_running_loop().call_later(0.05, self.__cancel, conn, call)

    async def prepare(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> PreparedStatement:
        """
        Create a prepared statement for a query asynchronously.

        Parameters
        ----------
        query : str
            Query to prepare.
        parameters : dict[str, Any]
            Parameters for the query.

        Returns
        -------
        PreparedStatement
            Prepared statement.

        """
        warnings.warn(
            "The use of separate prepare + execute of queries is deprecated. "
            "Please using a single call to the execute() API instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self._prepare(query, parameters)

    def close(self) -> None:
        """
        Close all connections and shutdown the thread pool.

        Note: Call to this method is optional. The connections and thread pool
        will be closed automatically when the instance is garbage collected.
        """
        for conn in self.connections:
            conn.close()

        self.executor.shutdown(wait=True)


class _Call:
    def __init__(self) -> None:
        self.cancelled = False
