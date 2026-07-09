from __future__ import annotations

from types import SimpleNamespace

import ladybug as lb
import ladybug.connection as lb_connection
import pytest


class _FakeResult:
    def isSuccess(self) -> bool:
        return True

    def hasNextQueryResult(self) -> bool:
        return False

    def close(self) -> None:
        return


class _FakePreparedStatement:
    def __init__(self, query: str, parameters: dict[str, object]):
        self.query = query
        self.parameters = dict(parameters)


class _FakePybindConnection:
    def __init__(self) -> None:
        self.prepare_calls: list[tuple[str, dict[str, object]]] = []
        self.execute_calls: list[tuple[_FakePreparedStatement, dict[str, object]]] = []
        self.query_calls: list[str] = []
        self.closed = False

    def prepare(
        self, query: str, parameters: dict[str, object]
    ) -> _FakePreparedStatement:
        self.prepare_calls.append((query, dict(parameters)))
        return _FakePreparedStatement(query, parameters)

    def execute(
        self, prepared: _FakePreparedStatement, parameters: dict[str, object]
    ) -> _FakeResult:
        self.execute_calls.append((prepared, dict(parameters)))
        return _FakeResult()

    def query(self, query: str) -> _FakeResult:
        self.query_calls.append(query)
        return _FakeResult()

    def close(self) -> None:
        self.closed = True


class _FakeBackendConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeDatabase:
    def __init__(self) -> None:
        self._use_pybind_backend = True
        self._database = object()
        self.is_closed = False
        self.registered_connections: list[lb.Connection] = []

    def _register_connection(self, connection: lb.Connection) -> None:
        self.registered_connections.append(connection)

    def _unregister_connection(self, connection: lb.Connection) -> None:
        self.registered_connections.remove(connection)

    def init_database(self) -> None:
        return None


@pytest.fixture
def fake_pybind_connection(monkeypatch: pytest.MonkeyPatch) -> _FakePybindConnection:
    fake_pybind = _FakePybindConnection()

    monkeypatch.setattr(lb_connection, "get_pybind_module", lambda: SimpleNamespace())
    monkeypatch.setattr(
        lb.Connection,
        "init_connection",
        lambda self: setattr(self, "_connection", _FakeBackendConnection()),
    )

    def _get_pybind_connection(self: lb.Connection) -> _FakePybindConnection:
        if self._py_connection is None:
            self._py_connection = fake_pybind
        return self._py_connection

    monkeypatch.setattr(lb.Connection, "_get_pybind_connection", _get_pybind_connection)
    return fake_pybind


def test_pybind_implicit_prepare_reuses_same_query(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    conn = lb.Connection(_FakeDatabase())

    conn.execute("RETURN $value", {"value": 1})
    conn.execute("RETURN $value", {"value": 2})

    assert fake_pybind_connection.query_calls == []
    assert len(fake_pybind_connection.prepare_calls) == 1
    assert [call[0].query for call in fake_pybind_connection.execute_calls] == [
        "RETURN $value",
        "RETURN $value",
    ]
    assert [call[1] for call in fake_pybind_connection.execute_calls] == [
        {"value": 1},
        {"value": 2},
    ]


def test_pybind_implicit_prepare_does_not_share_different_queries(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    conn = lb.Connection(_FakeDatabase())

    conn.execute("RETURN $value", {"value": 1})
    conn.execute("RETURN $other", {"other": 1})

    assert [call[0] for call in fake_pybind_connection.prepare_calls] == [
        "RETURN $value",
        "RETURN $other",
    ]


def test_pybind_implicit_prepare_segregates_by_integer_width(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    conn = lb.Connection(_FakeDatabase())

    conn.execute("RETURN $value", {"value": 1})
    conn.execute("RETURN $value", {"value": 1000})
    conn.execute("RETURN $value", {"value": 2})

    assert len(fake_pybind_connection.prepare_calls) == 2
    assert [call[1] for call in fake_pybind_connection.execute_calls] == [
        {"value": 1},
        {"value": 1000},
        {"value": 2},
    ]


def test_pybind_no_parameter_query_skips_prepare_cache(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    conn = lb.Connection(_FakeDatabase())

    conn.execute("RETURN 1")

    assert fake_pybind_connection.prepare_calls == []
    assert fake_pybind_connection.query_calls == ["RETURN 1"]


def test_pybind_close_clears_implicit_prepare_cache(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    conn = lb.Connection(_FakeDatabase())

    conn.execute("RETURN $value", {"value": 1})

    # Cache key is now (query, parameter-type signature) so that a
    # single query with different parameter shapes (e.g. MAP vs STRUCT)
    # does not share a prepared statement.
    assert len(conn._pybind_implicit_prepared_cache) == 1
    cached_key = next(iter(conn._pybind_implicit_prepared_cache))
    assert cached_key[0] == "RETURN $value"

    conn.close()

    assert conn._pybind_implicit_prepared_cache == {}
    assert fake_pybind_connection.closed is True


def test_pybind_implicit_prepare_segregates_by_parameter_shape(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    """The same query with different parameter shapes must not share a plan."""
    conn = lb.Connection(_FakeDatabase())

    # Same keys ``key``/``value`` with matching list lengths -> MAP.
    conn.execute("RETURN $st", {"st": {"key": [1, 2, 3], "value": [3, 7, 98]}})
    # First key is ``key1`` -> STRUCT.
    conn.execute("RETURN $st", {"st": {"key1": [1, 2, 3], "value": [3, 7, 98]}})
    # ``key``/``value`` but mismatched list lengths -> STRUCT (different
    # signature from the first call AND from the previous STRUCT because
    # the field names differ).
    conn.execute("RETURN $st", {"st": {"key": [1, 2], "value": [3, 7, 98, 4]}})

    # 3 distinct structural shapes -> 3 separate prepared statements.
    # Sharing any of them would either misbind the parameter or reroute
    # a new shape through a stale plan.
    assert len(fake_pybind_connection.prepare_calls) == 3
    assert all(call[0] == "RETURN $st" for call in fake_pybind_connection.prepare_calls)
    assert [call[1] for call in fake_pybind_connection.execute_calls] == [
        {"st": {"key": [1, 2, 3], "value": [3, 7, 98]}},
        {"st": {"key1": [1, 2, 3], "value": [3, 7, 98]}},
        {"st": {"key": [1, 2], "value": [3, 7, 98, 4]}},
    ]


def test_pybind_implicit_prepare_reuses_same_struct_shape(
    fake_pybind_connection: _FakePybindConnection,
) -> None:
    """Two calls that produce the same structural signature reuse the cache."""
    conn = lb.Connection(_FakeDatabase())

    # Same fields, different values -> identical signature.
    conn.execute("RETURN $st", {"st": {"key1": [1, 2, 3], "value": [3, 7, 98]}})
    conn.execute("RETURN $st", {"st": {"key1": [4, 5, 6], "value": [7, 8, 9]}})

    assert len(fake_pybind_connection.prepare_calls) == 1
    assert [call[1] for call in fake_pybind_connection.execute_calls] == [
        {"st": {"key1": [1, 2, 3], "value": [3, 7, 98]}},
        {"st": {"key1": [4, 5, 6], "value": [7, 8, 9]}},
    ]
