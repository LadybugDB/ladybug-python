from __future__ import annotations

from datetime import date, datetime

import ladybug as lb


def test_capi_backend_basic_query() -> None:
    db = lb.Database(":memory:")
    conn = lb.Connection(db)

    result = conn.execute("RETURN 1 AS a;")
    assert result.get_next() == [1]

    conn.close()
    db.close()


def test_capi_backend_parameter_binding() -> None:
    db = lb.Database(":memory:")
    conn = lb.Connection(db)

    assert conn.execute("RETURN $x + 1 AS v;", {"x": 1}).get_next()[0] == 2
    assert conn.execute("RETURN $d AS v;", {"d": date(2024, 1, 2)}).get_next()[0] == date(2024, 1, 2)
    assert conn.execute("RETURN $ts AS v;", {"ts": datetime(2024, 1, 2, 3, 4, 5)}).get_next()[0] == datetime(
        2024, 1, 2, 3, 4, 5
    )
    assert conn.execute("RETURN $v AS v;", {"v": {"a": 1, "b": [1, 2]}}).get_next()[0] == {
        "a": 1,
        "b": [1, 2],
    }

    conn.close()
    db.close()
