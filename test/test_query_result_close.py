import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
from conftest import get_db_file_path
from lbug_test_paths import LBUG_ROOT


def test_query_result_close(tmp_path: Path, build_dir: Path) -> None:
    db_path = get_db_file_path(tmp_path)
    code = dedent(f"""
        import sys
        sys.path.append(r"{build_dir!s}")

        import ladybug as lb
        db = lb.Database(r"{db_path!s}")
        conn = lb.Connection(db)
        conn.execute('''
          CREATE NODE TABLE person (
            ID INT64,
            fName STRING,
            gender INT64,
            isStudent BOOLEAN,
            isWorker BOOLEAN,
            age INT64,
            eyeSight DOUBLE,
            birthdate DATE,
            registerTime TIMESTAMP,
            lastJobDuration INTERVAL,
            workedHours INT64[],
            usedNames STRING[],
            courseScoresPerTerm INT64[][],
            grades INT64[4],
            height float,
            u UUID,
            PRIMARY KEY (ID))
        ''')
        conn.execute('COPY person FROM "{LBUG_ROOT}/dataset/tinysnb/vPerson.csv" (HEADER=true)')
        result = conn.execute("MATCH (a:person) WHERE a.ID = 0 RETURN a.isStudent;")
        # result.close()
    """)
    result = subprocess.run([sys.executable, "-c", code])
    assert result.returncode == 0


def test_pybind_native_close_is_idempotent(tmp_path: Path, build_dir: Path) -> None:
    db_path = get_db_file_path(tmp_path)
    code = dedent(f"""
        import gc
        import sys

        sys.path.append(r"{build_dir!s}")

        from ladybug._backend import get_pybind_module

        pybind = get_pybind_module()
        if pybind is None:
            raise SystemExit(77)

        db = pybind.Database(r"{db_path!s}")
        conn = pybind.Connection(db)
        result = conn.query("RETURN 1")

        result.close()
        result.close()
        try:
            result.hasNext()
        except RuntimeError as exc:
            assert "closed" in str(exc)
        else:
            raise AssertionError("closed query result remained usable")
        del result
        gc.collect()

        conn.close()
        conn.close()
        try:
            conn.query("RETURN 1")
        except RuntimeError as exc:
            assert "closed" in str(exc)
        else:
            raise AssertionError("closed connection remained usable")
        del conn
        gc.collect()

        db.close()
        db.close()
        del db
        gc.collect()

        db = pybind.Database(r"{db_path!s}.db_first")
        conn = pybind.Connection(db)
        result = conn.query("RETURN 1")
        statement = conn.prepare("RETURN 1")
        db.close()
        db.close()
        try:
            pybind.Connection(db)
        except RuntimeError as exc:
            assert "closed" in str(exc)
        else:
            raise AssertionError("connection opened on a closed database")
        del db
        gc.collect()
        del statement
        del result
        del conn
        gc.collect()

        db = pybind.Database(r"{db_path!s}.child_result")
        conn = pybind.Connection(db)
        result = conn.query("RETURN 1; RETURN 2;")
        child = result.getNextQueryResult()
        result.close()
        assert child.hasNext()
        assert child.getNext() == [2]
        conn.close()
        db.close()
        del child
        del result
        del conn
        del db
        gc.collect()
    """)
    result = subprocess.run([sys.executable, "-c", code])
    if result.returncode == 77:
        pytest.skip("pybind extension is not available")
    assert result.returncode == 0
