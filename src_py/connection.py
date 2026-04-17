from __future__ import annotations

import inspect
import re
import warnings
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from . import _lbug_capi as _lbug
from .prepared_statement import PreparedStatement
from .query_result import QueryResult

try:
    from . import _lbug as _lbug_pybind
except ImportError:  # pragma: no cover - pybind module may be unavailable in some builds
    _lbug_pybind = None

if TYPE_CHECKING:
    import sys
    from collections.abc import Callable
    from types import TracebackType

    from .database import Database
    from .types import Type

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


class Connection:
    """Connection to a database."""

    def __init__(self, database: Database, num_threads: int = 0):
        """
        Initialise lbug database connection.

        Parameters
        ----------
        database : Database
            Database to connect to.

        num_threads : int
            Maximum number of threads to use for executing queries.

        """
        self._connection: Any = None  # (type: _lbug.Connection from pybind11)
        self._py_connection: Any = None
        self.database = database
        self.num_threads = num_threads
        self.is_closed = False
        self._query_results: WeakSet[QueryResult] = WeakSet()
        self.database._register_connection(self)
        self.init_connection()

    def __getstate__(self) -> dict[str, Any]:
        state = {
            "database": self.database,
            "num_threads": self.num_threads,
            "_connection": None,
        }
        return state

    def init_connection(self) -> None:
        """Establish a connection to the database, if not already initalised."""
        if self.is_closed:
            error_msg = "Connection is closed."
            raise RuntimeError(error_msg)
        self.database.init_database()
        if self._connection is None:
            self._connection = _lbug.Connection(self.database._database, self.num_threads)  # type: ignore[union-attr]

    def set_max_threads_for_exec(self, num_threads: int) -> None:
        """
        Set the maximum number of threads for executing queries.

        Parameters
        ----------
        num_threads : int
            Maximum number of threads to use for executing queries.

        """
        self.init_connection()
        self._connection.set_max_threads_for_exec(num_threads)

    def _register_query_result(self, query_result: QueryResult) -> None:
        self._query_results.add(query_result)

    def _unregister_query_result(self, query_result: QueryResult) -> None:
        self._query_results.discard(query_result)

    def close(self) -> None:
        """
        Close the connection.

        Note: Call to this method is optional. The connection will be closed
        automatically when the object goes out of scope.
        """
        if self.is_closed:
            return

        for query_result in list(self._query_results):
            query_result.close()
        self._query_results.clear()

        if self._connection is not None and not self.database.is_closed:
            self._connection.close()
        self._connection = None

        if self._py_connection is not None and not self.database.is_closed:
            self._py_connection.close()
        self._py_connection = None
        self.is_closed = True
        self.database._unregister_connection(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _normalize_parameters_for_capi(
        self,
        query: str,
        parameters: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        normalized_query = query
        normalized_params = dict(parameters)

        for key, value in list(normalized_params.items()):
            if not isinstance(key, str):
                msg = f"Parameter name must be of type string but got {type(key)}"
                raise RuntimeError(msg)

            if isinstance(value, (bytes, bytearray, memoryview)):
                binary = bytes(value)
                normalized_params[key] = "".join(f"\\x{byte:02x}" for byte in binary)
                pattern = rf"(?i)(?<!BLOB\()\${re.escape(key)}\b"
                normalized_query = re.sub(pattern, f"BLOB(${key})", normalized_query)

        return normalized_query, normalized_params

    def _is_python_scan_object(self, value: Any) -> bool:
        module_name = type(value).__module__
        return (
            module_name.startswith("pandas")
            or module_name.startswith("polars")
            or module_name.startswith("pyarrow")
        )

    def _has_scan_pattern(self, query: str) -> bool:
        stripped = query.lstrip()
        if not (stripped.upper().startswith("LOAD ") or stripped.upper().startswith("COPY ")):
            return False
        return re.search(r"(?i)\bFROM\b", query) is not None

    def _should_use_pybind_for_scan(self, query: str, parameters: dict[str, Any]) -> bool:
        if _lbug_pybind is None:
            return False
        if not self._has_scan_pattern(query):
            return False

        if re.search(r"(?i)\bFROM\s+[A-Za-z_][A-Za-z0-9_]*\b", query):
            return True

        for key, value in parameters.items():
            if not isinstance(key, str):
                continue
            if re.search(rf"(?i)\bFROM\s+\${re.escape(key)}\b", query):
                return True
            if self._is_python_scan_object(value):
                return True
        return False

    def _get_pybind_connection(self) -> Any | None:
        if _lbug_pybind is None:
            return None
        self.database.init_database()
        pybind_db = self.database.init_pybind_database()
        if pybind_db is None:
            return None
        if self._py_connection is None:
            self._py_connection = _lbug_pybind.Connection(pybind_db, self.num_threads)
        return self._py_connection

    def _execute_with_pybind(
        self,
        query: str,
        parameters: dict[str, Any],
    ) -> Any:
        py_connection = self._get_pybind_connection()
        if py_connection is None:
            return None

        if len(parameters) == 0:
            return py_connection.query(query)

        prepared = py_connection.prepare(query, {})
        return py_connection.execute(prepared, parameters)

    def _maybe_raise_scan_unsupported_object(self, query: str) -> None:
        match = re.search(r"\bLOAD\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)\b", query, re.IGNORECASE)
        if not match:
            return

        var_name = match.group(1)
        frame = inspect.currentframe()
        if frame is None or frame.f_back is None:
            return

        caller = frame.f_back.f_back
        if caller is None:
            return

        scope = {**caller.f_globals, **caller.f_locals}
        if var_name not in scope:
            return

        value = scope[var_name]
        module_name = type(value).__module__
        if module_name.startswith("pandas") or module_name.startswith("polars") or module_name.startswith("pyarrow"):
            return

        msg = (
            "Binder exception: Attempted to scan from unsupported python object. "
            "Can only scan from pandas/polars dataframes and pyarrow tables."
        )
        raise RuntimeError(msg)

    def execute(
        self,
        query: str | PreparedStatement,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult | list[QueryResult]:
        """
        Execute a query.

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

        """
        if parameters is None:
            parameters = {}

        self.init_connection()
        if not isinstance(parameters, dict):
            msg = f"Parameters must be a dict; found {type(parameters)}."
            raise RuntimeError(msg)  # noqa: TRY004

        if isinstance(query, str) and self._should_use_pybind_for_scan(query, parameters):
            query_result_internal = self._execute_with_pybind(query, parameters)
            if query_result_internal is None:
                msg = "Scan from python objects requires pybind backend support."
                raise RuntimeError(msg)
        elif len(parameters) == 0 and isinstance(query, str):
            self._maybe_raise_scan_unsupported_object(query)
            query_result_internal = self._connection.query(query)
        else:
            if isinstance(query, str):
                query, parameters = self._normalize_parameters_for_capi(query, parameters)
            prepared_statement = (
                self._prepare(query, parameters) if isinstance(query, str) else query
            )
            query_result_internal = self._connection.execute(
                prepared_statement._prepared_statement, parameters
            )
        if not query_result_internal.isSuccess():
            raise RuntimeError(query_result_internal.getErrorMessage())
        current_query_result = QueryResult(self, query_result_internal)
        self._register_query_result(current_query_result)
        if not query_result_internal.hasNextQueryResult():
            return current_query_result
        all_query_results = [current_query_result]
        while query_result_internal.hasNextQueryResult():
            query_result_internal = query_result_internal.getNextQueryResult()
            if not query_result_internal.isSuccess():
                raise RuntimeError(query_result_internal.getErrorMessage())
            next_query_result = QueryResult(self, query_result_internal)
            self._register_query_result(next_query_result)
            all_query_results.append(next_query_result)
        return all_query_results

    def _prepare(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> PreparedStatement:
        """
        The only parameters supported during prepare are dataframes.
        Any remaining parameters will be ignored and should be passed to execute().
        """  # noqa: D401
        return PreparedStatement(self, query, parameters)

    def prepare(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> PreparedStatement:
        """
        Create a prepared statement for a query.

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
        return self._prepare(query, parameters)

    def _get_node_property_names(self, table_name: str) -> dict[str, Any]:
        LIST_START_SYMBOL = "["
        LIST_END_SYMBOL = "]"
        self.init_connection()
        query_result = self.execute(f"CALL table_info('{table_name}') RETURN *;")
        results = {}
        while query_result.has_next():
            row = query_result.get_next()
            prop_name = row[1]
            prop_type = row[2]
            is_primary_key = row[4] is True
            dimension = prop_type.count(LIST_START_SYMBOL)
            splitted = prop_type.split(LIST_START_SYMBOL)
            shape = []
            for s in splitted:
                if LIST_END_SYMBOL not in s:
                    continue
                s = s.split(LIST_END_SYMBOL)[0]
                if s != "":
                    shape.append(int(s))
            prop_type = splitted[0]
            results[prop_name] = {
                "type": prop_type,
                "dimension": dimension,
                "is_primary_key": is_primary_key,
            }
            if len(shape) > 0:
                results[prop_name]["shape"] = tuple(shape)
        return results

    def _get_node_table_names(self) -> list[Any]:
        results = []
        self.init_connection()
        query_result = self.execute("CALL show_tables() RETURN *;")
        while query_result.has_next():
            row = query_result.get_next()
            if row[2] == "NODE":
                results.append(row[1])
        return results

    def _get_rel_table_names(self) -> list[dict[str, Any]]:
        results = []
        self.init_connection()
        tables_result = self.execute("CALL show_tables() RETURN *;")
        while tables_result.has_next():
            row = tables_result.get_next()
            if row[2] == "REL":
                name = row[1]
                connections_result = self.execute(
                    f"CALL show_connection({name!r}) RETURN *;"
                )
                src_dst_row = connections_result.get_next()
                src_node = src_dst_row[0]
                dst_node = src_dst_row[1]
                results.append({"name": name, "src": src_node, "dst": dst_node})
        return results

    def set_query_timeout(self, timeout_in_ms: int) -> None:
        """
        Set the query timeout value in ms for executing queries.

        Parameters
        ----------
        timeout_in_ms : int
            query timeout value in ms for executing queries.

        """
        self.init_connection()
        self._connection.set_query_timeout(timeout_in_ms)

    def interrupt(self) -> None:
        """
        Interrupts execution of the current query.

        If there is no currently executing query, this function does nothing.
        """
        self._connection.interrupt()

    def create_function(
        self,
        name: str,
        udf: Callable[[...], Any],
        params_type: list[Type | str] | None = None,
        return_type: Type | str = "",
        *,
        default_null_handling: bool = True,
        catch_exceptions: bool = False,
    ) -> None:
        """
        Set a User Defined Function (UDF) for use in cypher queries.

        Parameters
        ----------
        name: str
            name of function

        udf: Callable[[...], Any]
            function to be executed

        params_type: Optional[list[Type]]
            list of Type enums to describe the input parameters

        return_type: Optional[Type]
            a Type enum to describe the returned value

        default_null_handling: Optional[bool]
            if true, when any parameter is null, the resulting value will be null

        catch_exceptions: Optional[bool]
            if true, when an exception is thrown from python, the function output will be null
            Otherwise, the exception will be rethrown
        """
        if params_type is None:
            params_type = []
        parsed_params_type = [x if type(x) is str else x.value for x in params_type]
        if type(return_type) is not str:
            return_type = return_type.value

        try:
            self._connection.create_function(
                name=name,
                udf=udf,
                params_type=parsed_params_type,
                return_value=return_type,
                default_null=default_null_handling,
                catch_exceptions=catch_exceptions,
            )
        except NotImplementedError:
            py_connection = self._get_pybind_connection()
            if py_connection is None:
                raise
            py_connection.create_function(
                name=name,
                udf=udf,
                params_type=parsed_params_type,
                return_value=return_type,
                default_null=default_null_handling,
                catch_exceptions=catch_exceptions,
            )

    def remove_function(self, name: str) -> None:
        """
        Remove a User Defined Function (UDF).

        Parameters
        ----------
        name: str
            name of function to be removed.
        """
        try:
            self._connection.remove_function(name)
        except NotImplementedError:
            py_connection = self._get_pybind_connection()
            if py_connection is None:
                raise
            py_connection.remove_function(name)

    def create_arrow_table(
        self,
        table_name: str,
        dataframe: Any,
    ) -> QueryResult:
        """
        Create an Arrow memory-backed table from a DataFrame.

        Parameters
        ----------
        table_name : str
            Name of the table to create.

        dataframe : Any
            A pandas DataFrame, polars DataFrame, or PyArrow table.

        Returns
        -------
        QueryResult
            Result of the table creation query.

        """
        self.init_connection()
        try:
            query_result_internal = self._connection.create_arrow_table(
                table_name, dataframe
            )
        except NotImplementedError:
            py_connection = self._get_pybind_connection()
            if py_connection is None:
                raise
            query_result_internal = py_connection.create_arrow_table(table_name, dataframe)
        if not query_result_internal.isSuccess():
            raise RuntimeError(query_result_internal.getErrorMessage())
        return QueryResult(self, query_result_internal)

    def drop_arrow_table(self, table_name: str) -> QueryResult:
        """
        Drop an Arrow memory-backed table.

        Parameters
        ----------
        table_name : str
            Name of the table to drop.

        Returns
        -------
        QueryResult
            Result of the drop table query.

        """
        self.init_connection()
        try:
            query_result_internal = self._connection.drop_arrow_table(table_name)
        except NotImplementedError:
            py_connection = self._get_pybind_connection()
            if py_connection is None:
                raise
            query_result_internal = py_connection.drop_arrow_table(table_name)
        if not query_result_internal.isSuccess():
            raise RuntimeError(query_result_internal.getErrorMessage())
        return QueryResult(self, query_result_internal)

    def create_arrow_rel_table(
        self,
        table_name: str,
        dataframe: Any,
        src_table_name: str,
        dst_table_name: str,
    ) -> QueryResult:
        """
        Create an Arrow memory-backed relationship table from a DataFrame.

        Parameters
        ----------
        table_name : str
            Name of the relationship table to create.

        dataframe : Any
            A pandas DataFrame, polars DataFrame, or PyArrow table.

        src_table_name : str
            Source node table name in the FROM/TO pair.

        dst_table_name : str
            Destination node table name in the FROM/TO pair.

        Returns
        -------
        QueryResult
            Result of the table creation query.

        """
        self.init_connection()
        try:
            query_result_internal = self._connection.create_arrow_rel_table(
                table_name,
                dataframe,
                src_table_name,
                dst_table_name,
            )
        except NotImplementedError:
            py_connection = self._get_pybind_connection()
            if py_connection is None:
                raise
            query_result_internal = py_connection.create_arrow_rel_table(
                table_name,
                dataframe,
                src_table_name,
                dst_table_name,
            )
        if not query_result_internal.isSuccess():
            raise RuntimeError(query_result_internal.getErrorMessage())
        return QueryResult(self, query_result_internal)
