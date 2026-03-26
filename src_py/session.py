"""Remote session client for Lbug HTTP Service Mode."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sys
    from collections.abc import Iterator
    from types import TracebackType
    from typing import Any

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


class RemoteQueryResult:
    """Stores the result of a remote query execution over HTTP."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._columns: list[str] = data.get("columns", [])
        self._rows: list[list[str]] = data.get("rows", [])
        self._num_rows: int = data.get("numRows", len(self._rows))
        self._compiling_time: float = data.get("compilingTime", 0.0)
        self._execution_time: float = data.get("executionTime", 0.0)
        self._error: str | None = data.get("error")
        self._cursor = 0
        self.is_closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Iterator[list[str]]:
        return self

    def __next__(self) -> list[str]:
        if self.has_next():
            return self.get_next()
        raise StopIteration

    def is_success(self) -> bool:
        """Check if the query executed successfully."""
        return self._error is None

    def get_error_message(self) -> str | None:
        """Get the error message if the query failed."""
        return self._error

    def has_next(self) -> bool:
        """Check if there are more rows to read."""
        self._check_closed()
        return self._cursor < len(self._rows)

    def get_next(self) -> list[str]:
        """Get the next row."""
        self._check_closed()
        if self._cursor >= len(self._rows):
            msg = "No more rows"
            raise StopIteration(msg)
        row = self._rows[self._cursor]
        self._cursor += 1
        return row

    def get_all(self) -> list[list[str]]:
        """Get all remaining rows."""
        return list(self)

    def get_column_names(self) -> list[str]:
        """Get column names."""
        return self._columns

    def get_num_tuples(self) -> int:
        """Get total number of rows."""
        return self._num_rows

    def get_compiling_time(self) -> float:
        """Get query compiling time in ms."""
        return self._compiling_time

    def get_execution_time(self) -> float:
        """Get query execution time in ms."""
        return self._execution_time

    def reset_iterator(self) -> None:
        """Reset the row iterator to the beginning."""
        self._cursor = 0

    def get_as_df(self) -> Any:
        """
        Get the query result as a Pandas DataFrame.

        Returns
        -------
        pandas.DataFrame
            Query result as a Pandas DataFrame.
        """
        import pandas as pd

        self._check_closed()
        return pd.DataFrame(self._rows, columns=self._columns)

    def close(self) -> None:
        """Close the query result."""
        self.is_closed = True

    def _check_closed(self) -> None:
        if self.is_closed:
            msg = "Query result is closed"
            raise RuntimeError(msg)

    def __repr__(self) -> str:
        if self._error:
            return f"RemoteQueryResult(error={self._error!r})"
        return f"RemoteQueryResult(columns={self._columns}, numRows={self._num_rows})"


class Session:
    """
    HTTP client session for connecting to a Lbug Service Mode server.

    Example
    -------
    >>> session = Session("http://localhost:8000")
    >>> result = session.execute("MATCH (n:Person) RETURN n.name, n.age")
    >>> while result.has_next():
    ...     print(result.get_next())
    >>> session.close()

    Or as a context manager:

    >>> with Session("http://localhost:8000") as session:
    ...     result = session.execute("MATCH (n:Person) RETURN n.name")
    ...     print(result.get_all())
    """

    def __init__(self, endpoint: str = "http://localhost:8000", timeout: float = 30.0) -> None:
        """
        Create a session connected to a Lbug Service Mode server.

        Parameters
        ----------
        endpoint : str
            Base URL of the server (e.g. "http://localhost:8000").
        timeout : float
            Request timeout in seconds.
        """
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._closed = False
        # Use a no-proxy opener for localhost connections
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        # Verify connectivity
        try:
            self.health()
        except Exception as e:
            msg = f"Failed to connect to Lbug server at {self._endpoint}: {e}"
            raise ConnectionError(msg) from e

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        self.close()

    def execute(self, query: str) -> RemoteQueryResult:
        """
        Execute a Cypher query.

        Parameters
        ----------
        query : str
            The Cypher query to execute.

        Returns
        -------
        RemoteQueryResult
            The query result.
        """
        self._check_closed()
        payload = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._endpoint}/cypher",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        data = self._send(req)
        result = RemoteQueryResult(data)
        if not result.is_success():
            msg = result.get_error_message()
            raise RuntimeError(msg)
        return result

    def health(self) -> dict[str, Any]:
        """
        Check server health.

        Returns
        -------
        dict
            Server health status.
        """
        req = urllib.request.Request(f"{self._endpoint}/health")
        return self._send(req)

    def schema(self) -> RemoteQueryResult:
        """
        Get database schema.

        Returns
        -------
        RemoteQueryResult
            Schema information as a query result.
        """
        self._check_closed()
        req = urllib.request.Request(f"{self._endpoint}/schema")
        data = self._send(req)
        return RemoteQueryResult(data)

    def close(self) -> None:
        """Close the session."""
        self._closed = True

    def _send(self, req: urllib.request.Request) -> dict[str, Any]:
        """Send an HTTP request and return parsed JSON response."""
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise RuntimeError(f"HTTP {e.code}: {body}") from e

    def _check_closed(self) -> None:
        if self._closed:
            msg = "Session is closed"
            raise RuntimeError(msg)

    def __repr__(self) -> str:
        state = "closed" if self._closed else "connected"
        return f"Session(endpoint={self._endpoint!r}, {state})"
