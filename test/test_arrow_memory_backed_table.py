import polars as pl
import pyarrow as pa
import pytest
from type_aliases import ConnDB


def test_arrow_memory_backed_table_basic(conn_db_empty: ConnDB) -> None:
    """Test basic Arrow memory-backed table creation and querying with polars."""
    conn, _ = conn_db_empty

    # Create a polars DataFrame
    df = pl.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
            "age": [25, 30, 35, 40, 45],
            "salary": [50000.0, 60000.0, 75000.0, 90000.0, 100000.0],
        }
    )

    # Register the Arrow table
    conn.create_arrow_table("employees", df)

    # Query all data
    result = conn.execute(
        "MATCH (n:employees) RETURN n.id, n.name, n.age, n.salary ORDER BY n.id"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 5
    assert rows[0] == [1, "Alice", 25, 50000.0]
    assert rows[1] == [2, "Bob", 30, 60000.0]
    assert rows[2] == [3, "Charlie", 35, 75000.0]
    assert rows[3] == [4, "Diana", 40, 90000.0]
    assert rows[4] == [5, "Eve", 45, 100000.0]

    # Clean up
    conn.drop_arrow_table("employees")


def test_arrow_memory_backed_table_filtering(conn_db_empty: ConnDB) -> None:
    """Test filtering rows from an Arrow memory-backed table using Cypher."""
    conn, _ = conn_db_empty

    # Create a polars DataFrame with more data
    df = pl.DataFrame(
        {
            "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "name": [
                "Alice",
                "Bob",
                "Charlie",
                "Diana",
                "Eve",
                "Frank",
                "Grace",
                "Henry",
                "Ivy",
                "Jack",
            ],
            "age": [25, 30, 35, 40, 45, 28, 33, 38, 42, 50],
            "department": [
                "Engineering",
                "Sales",
                "Engineering",
                "HR",
                "Sales",
                "Engineering",
                "HR",
                "Sales",
                "Engineering",
                "HR",
            ],
            "salary": [
                50000.0,
                60000.0,
                75000.0,
                55000.0,
                70000.0,
                52000.0,
                58000.0,
                65000.0,
                80000.0,
                60000.0,
            ],
        }
    )

    # Register the Arrow table
    conn.create_arrow_table("staff", df)

    # Test 1: Filter by age > 35
    result = conn.execute(
        "MATCH (n:staff) WHERE n.age > 35 RETURN n.name, n.age ORDER BY n.age"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 5
    assert rows[0] == ["Henry", 38]
    assert rows[1] == ["Diana", 40]
    assert rows[2] == ["Ivy", 42]
    assert rows[3] == ["Eve", 45]
    assert rows[4] == ["Jack", 50]

    # Test 2: Filter by department
    result = conn.execute(
        "MATCH (n:staff) WHERE n.department = 'Engineering' RETURN n.name, n.department ORDER BY n.id"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 4
    assert rows[0] == ["Alice", "Engineering"]
    assert rows[1] == ["Charlie", "Engineering"]
    assert rows[2] == ["Frank", "Engineering"]
    assert rows[3] == ["Ivy", "Engineering"]

    # Test 3: Filter by salary range
    result = conn.execute(
        "MATCH (n:staff) WHERE n.salary >= 60000.0 AND n.salary <= 75000.0 "
        "RETURN n.name, n.salary ORDER BY n.salary"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 5
    assert rows[0] == ["Bob", 60000.0]
    assert rows[1] == ["Jack", 60000.0]
    assert rows[2] == ["Henry", 65000.0]
    assert rows[3] == ["Eve", 70000.0]
    assert rows[4] == ["Charlie", 75000.0]

    # Test 4: Complex filter with AND/OR
    result = conn.execute(
        "MATCH (n:staff) WHERE (n.department = 'Engineering' AND n.salary > 60000.0) "
        "OR n.age > 45 RETURN n.name, n.department, n.salary, n.age ORDER BY n.id"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 3
    assert rows[0] == ["Charlie", "Engineering", 75000.0, 35]
    assert rows[1] == ["Ivy", "Engineering", 80000.0, 42]
    assert rows[2] == ["Jack", "HR", 60000.0, 50]

    # Clean up
    conn.drop_arrow_table("staff")


def test_arrow_memory_backed_table_with_pandas(conn_db_empty: ConnDB) -> None:
    """Test Arrow memory-backed table with pandas DataFrame."""
    conn, _ = conn_db_empty

    pd = pytest.importorskip("pandas")

    # Create a pandas DataFrame
    df = pd.DataFrame(
        {
            "product_id": [101, 102, 103, 104, 105],
            "product_name": ["Widget A", "Widget B", "Gadget X", "Gadget Y", "Tool Z"],
            "price": [9.99, 14.99, 29.99, 34.99, 49.99],
            "in_stock": [True, True, False, True, False],
        }
    )

    # Register the Arrow table
    conn.create_arrow_table("products", df)

    # Query with filter
    result = conn.execute(
        "MATCH (n:products) WHERE n.in_stock = true AND n.price < 20.0 "
        "RETURN n.product_name, n.price ORDER BY n.price"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 2
    assert rows[0] == ["Widget A", 9.99]
    assert rows[1] == ["Widget B", 14.99]

    # Clean up
    conn.drop_arrow_table("products")


def test_arrow_memory_backed_table_with_pyarrow(conn_db_empty: ConnDB) -> None:
    """Test Arrow memory-backed table with native PyArrow table."""
    conn, _ = conn_db_empty

    import pyarrow as pa

    # Create a PyArrow table directly
    table = pa.table(
        {
            "city": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"],
            "population": [8419000, 3980000, 2716000, 2328000, 1690000],
            "area_sq_miles": [302.6, 468.7, 227.3, 637.5, 517.6],
        }
    )

    # Register the Arrow table
    conn.create_arrow_table("cities", table)

    # Query with filter
    result = conn.execute(
        "MATCH (n:cities) WHERE n.population > 2000000 AND n.area_sq_miles < 400 "
        "RETURN n.city, n.population, n.area_sq_miles ORDER BY n.population DESC"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 2
    assert rows[0] == ["New York", 8419000, 302.6]
    assert rows[1] == ["Chicago", 2716000, 227.3]

    # Clean up
    conn.drop_arrow_table("cities")


def test_arrow_memory_backed_table_empty_result(conn_db_empty: ConnDB) -> None:
    """Test filtering that returns no results."""
    conn, _ = conn_db_empty

    df = pl.DataFrame(
        {
            "id": [1, 2, 3],
            "value": [10, 20, 30],
        }
    )

    conn.create_arrow_table("data", df)

    # Filter that matches nothing
    result = conn.execute("MATCH (n:data) WHERE n.value > 100 RETURN n.id")
    assert not result.has_next()

    # Clean up
    conn.drop_arrow_table("data")


def test_arrow_memory_backed_table_count(conn_db_empty: ConnDB) -> None:
    """Test aggregation on Arrow memory-backed table."""
    conn, _ = conn_db_empty

    df = pl.DataFrame(
        {
            "category": ["A", "B", "A", "C", "B", "A", "C", "B"],
            "amount": [100, 200, 150, 300, 250, 120, 280, 180],
        }
    )

    conn.create_arrow_table("transactions", df)

    # Count by category
    result = conn.execute(
        "MATCH (n:transactions) RETURN n.category, COUNT(*) as cnt ORDER BY n.category"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert len(rows) == 3
    assert rows[0] == ["A", 3]
    assert rows[1] == ["B", 3]
    assert rows[2] == ["C", 2]

    # Clean up
    conn.drop_arrow_table("transactions")


def test_arrow_memory_backed_arrow_node_and_rel_table(conn_db_empty: ConnDB) -> None:
    """Test an Arrow memory-backed relationship over Arrow-backed nodes."""
    conn, _ = conn_db_empty

    pa = pytest.importorskip("pyarrow")

    people = pa.Table.from_arrays(
        [
            pa.array([1, 2, 3], type=pa.int64()),
            pa.array(["Alice", "Bob", "Carol"], type=pa.string()),
        ],
        names=["id", "name"],
    )
    conn.create_arrow_table("arrow_people", people)

    knows = pa.Table.from_arrays(
        [
            pa.array([1, 1, 2], type=pa.int64()),
            pa.array([2, 3, 3], type=pa.int64()),
            pa.array([10, 20, 30], type=pa.int64()),
        ],
        names=["from", "to", "weight"],
    )
    conn.create_arrow_rel_table("arrow_knows", knows, "arrow_people", "arrow_people")

    result = conn.execute(
        "MATCH (a:arrow_people)-[r:arrow_knows]->(b:arrow_people) "
        "RETURN a.name, b.name, r.weight ORDER BY a.id, b.id"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert rows == [
        ["Alice", "Bob", 10],
        ["Alice", "Carol", 20],
        ["Bob", "Carol", 30],
    ]

    result = conn.execute(
        "MATCH (:arrow_people)-[r:arrow_knows]->(:arrow_people) "
        "RETURN COUNT(*), SUM(r.weight)"
    )
    assert result.get_next() == [3, 60]
    assert not result.has_next()

    result = conn.execute(
        "MATCH (a:arrow_people)-[r:arrow_knows]->(b:arrow_people) "
        "WHERE r.weight >= 20 "
        "RETURN a.name, b.name, r.weight ORDER BY r.weight"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert rows == [
        ["Alice", "Carol", 20],
        ["Bob", "Carol", 30],
    ]

    conn.drop_arrow_table("arrow_knows")
    conn.drop_arrow_table("arrow_people")


def test_arrow_memory_backed_native_node_and_arrow_rel_table(
    conn_db_empty: ConnDB,
) -> None:
    """Test an Arrow memory-backed relationship over native node tables."""
    conn, _ = conn_db_empty

    pa = pytest.importorskip("pyarrow")

    conn.execute(
        "CREATE NODE TABLE native_people(id INT64, name STRING, PRIMARY KEY(id));"
        "CREATE (:native_people {id: 1, name: 'Alice'});"
        "CREATE (:native_people {id: 2, name: 'Bob'});"
        "CREATE (:native_people {id: 3, name: 'Carol'});"
    )

    knows = pa.Table.from_arrays(
        [
            pa.array([1, 1, 2], type=pa.int64()),
            pa.array([2, 3, 3], type=pa.int64()),
            pa.array([10, 20, 30], type=pa.int64()),
        ],
        names=["from", "to", "weight"],
    )
    conn.create_arrow_rel_table(
        "native_people_arrow_knows", knows, "native_people", "native_people"
    )

    result = conn.execute(
        "MATCH (a:native_people)-[r:native_people_arrow_knows]->(b:native_people) "
        "RETURN a.name, b.name, r.weight ORDER BY a.id, b.id"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert rows == [
        ["Alice", "Bob", 10],
        ["Alice", "Carol", 20],
        ["Bob", "Carol", 30],
    ]

    result = conn.execute(
        "MATCH (:native_people)-[r:native_people_arrow_knows]->(:native_people) "
        "RETURN COUNT(*), SUM(r.weight)"
    )
    assert result.get_next() == [3, 60]
    assert not result.has_next()

    result = conn.execute(
        "MATCH (a:native_people)-[r:native_people_arrow_knows]->(b:native_people) "
        "WHERE r.weight >= 20 "
        "RETURN a.name, b.name, r.weight ORDER BY r.weight"
    )
    rows = []
    while result.has_next():
        rows.append(result.get_next())

    assert rows == [
        ["Alice", "Carol", 20],
        ["Bob", "Carol", 30],
    ]

    conn.drop_arrow_table("native_people_arrow_knows")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for CSR tests
# ─────────────────────────────────────────────────────────────────────────────


def _make_csr_node_table(conn, table_name: str) -> None:
    """4 Arrow nodes: offsets 0=A, 1=B, 2=C, 3=D (id=0..3)."""
    df = pl.DataFrame({"id": [0, 1, 2, 3]})
    conn.create_arrow_table(table_name, df)


def _make_csr_fwd_indices() -> pa.Table:
    """FWD adjacency: (dst=1,w=10),(dst=2,w=20),(dst=2,w=30),(dst=3,w=40)."""
    return pa.table(
        {
            "dst_offset": pa.array([1, 2, 2, 3], type=pa.uint64()),
            "weight": pa.array([10, 20, 30, 40], type=pa.int64()),
        }
    )


def _make_csr_fwd_indptr() -> pa.Table:
    """FWD indptr: node0→edges[0..1], node1→edges[2], node2→edges[3], node3→(empty)."""
    return pa.table({"v": pa.array([0, 2, 3, 4, 4], type=pa.uint64())})


def _make_csr_bwd_indices() -> pa.Table:
    """BWD adjacency: (src=0,w=10),(src=0,w=20),(src=1,w=30),(src=2,w=40)."""
    return pa.table(
        {
            "src_offset": pa.array([0, 0, 1, 2], type=pa.uint64()),
            "weight": pa.array([10, 20, 30, 40], type=pa.int64()),
        }
    )


def _make_csr_bwd_indptr() -> pa.Table:
    """BWD indptr: node0→(empty), node1→edges[0], node2→edges[1..2], node3→edges[3]."""
    return pa.table({"v": pa.array([0, 0, 1, 3, 4], type=pa.uint64())})


# ─────────────────────────────────────────────────────────────────────────────
# CSR tests
# ─────────────────────────────────────────────────────────────────────────────


def test_arrow_csr_rel_table_fwd_only(conn_db_empty: ConnDB) -> None:
    """FWD-only CSR table: count=4, sum=100."""
    conn, _ = conn_db_empty
    _make_csr_node_table(conn, "csr_node")

    conn.create_arrow_csr_rel_table(
        "csr_rel",
        "csr_node",
        "csr_node",
        _make_csr_fwd_indices(),
        _make_csr_fwd_indptr(),
    )

    result = conn.execute("MATCH (:csr_node)-[:csr_rel]->(:csr_node) RETURN count(*)")
    assert result.get_next()[0] == 4

    result = conn.execute(
        "MATCH (:csr_node)-[e:csr_rel]->(:csr_node) RETURN sum(e.weight)"
    )
    assert result.get_next()[0] == 100

    conn.drop_arrow_table("csr_rel")
    conn.drop_arrow_table("csr_node")


def test_arrow_csr_rel_table_with_bwd(conn_db_empty: ConnDB) -> None:
    """CSR table with explicit BWD adjacency: BWD count=4, BWD sum=100."""
    conn, _ = conn_db_empty
    _make_csr_node_table(conn, "csr_node")

    conn.create_arrow_csr_rel_table(
        "csr_rel",
        "csr_node",
        "csr_node",
        _make_csr_fwd_indices(),
        _make_csr_fwd_indptr(),
        _make_csr_bwd_indices(),
        _make_csr_bwd_indptr(),
    )

    result = conn.execute("MATCH (:csr_node)<-[:csr_rel]-(:csr_node) RETURN count(*)")
    assert result.get_next()[0] == 4

    result = conn.execute(
        "MATCH (:csr_node)<-[e:csr_rel]-(:csr_node) RETURN sum(e.weight)"
    )
    assert result.get_next()[0] == 100

    conn.drop_arrow_table("csr_rel")
    conn.drop_arrow_table("csr_node")


def test_arrow_csr_rel_table_bwd_fallback(conn_db_empty: ConnDB) -> None:
    """CSR table without BWD data: fallback full-scan returns correct BWD count."""
    conn, _ = conn_db_empty
    _make_csr_node_table(conn, "csr_node")

    conn.create_arrow_csr_rel_table(
        "csr_rel",
        "csr_node",
        "csr_node",
        _make_csr_fwd_indices(),
        _make_csr_fwd_indptr(),
    )

    result = conn.execute("MATCH (:csr_node)<-[:csr_rel]-(:csr_node) RETURN count(*)")
    assert result.get_next()[0] == 4

    conn.drop_arrow_table("csr_rel")
    conn.drop_arrow_table("csr_node")


def test_arrow_csr_rel_table_partial_bwd_raises(conn_db_empty: ConnDB) -> None:
    """Providing only bwd_indices or only bwd_indptr must raise ValueError."""
    conn, _ = conn_db_empty
    _make_csr_node_table(conn, "csr_node")

    with pytest.raises((ValueError, RuntimeError)):
        conn.create_arrow_csr_rel_table(
            "csr_rel",
            "csr_node",
            "csr_node",
            _make_csr_fwd_indices(),
            _make_csr_fwd_indptr(),
            bwd_indices=_make_csr_bwd_indices(),
            bwd_indptr=None,
        )

    with pytest.raises((ValueError, RuntimeError)):
        conn.create_arrow_csr_rel_table(
            "csr_rel2",
            "csr_node",
            "csr_node",
            _make_csr_fwd_indices(),
            _make_csr_fwd_indptr(),
            bwd_indices=None,
            bwd_indptr=_make_csr_bwd_indptr(),
        )

    conn.drop_arrow_table("csr_node")


def test_arrow_csr_over_native_node_table_raises(conn_db_empty: ConnDB) -> None:
    """CSR rel table over a native (non-Arrow) node table must fail."""
    conn, _ = conn_db_empty
    conn.execute(
        "CREATE NODE TABLE native_node(id INT64, PRIMARY KEY(id));"
        "CREATE (:native_node {id: 0});"
        "CREATE (:native_node {id: 1});"
    )

    with pytest.raises((RuntimeError, Exception)):
        conn.create_arrow_csr_rel_table(
            "csr_rel",
            "native_node",
            "native_node",
            _make_csr_fwd_indices(),
            _make_csr_fwd_indptr(),
        )
