"""
Register icebug-disk Parquet files as Arrow memory-backed tables.

The example keeps the data in PyArrow tables and exposes it to Ladybug as
ice-mem/Arrow tables. Relationship tables can be either FLAT or CSR.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import ladybug as lb
import pyarrow.parquet as pq


def register_flat(
    conn: lb.Connection,
    data_dir: Path,
    node_table: str,
    rel_table: str,
    src_table: str,
    dst_table: str,
) -> None:
    """Register FLAT icebug-disk Parquet files as Arrow memory-backed tables."""
    nodes = pq.read_table(data_dir / f"nodes_{node_table}.parquet")
    rels = pq.read_table(data_dir / f"rels_{rel_table}.parquet")

    conn.create_arrow_table(node_table, nodes)
    conn.create_arrow_rel_table(
        rel_table,
        rels,
        src_table,
        dst_table,
        layout=lb.ArrowRelTableLayout.FLAT,
    )


def register_csr(
    conn: lb.Connection,
    data_dir: Path,
    node_table: str,
    rel_table: str,
    src_table: str,
    dst_table: str,
) -> None:
    """Register CSR icebug-disk Parquet files as Arrow memory-backed tables."""
    nodes = pq.read_table(data_dir / f"nodes_{node_table}.parquet")
    indices = pq.read_table(data_dir / f"indices_{rel_table}.parquet")
    indptr = pq.read_table(data_dir / f"indptr_{rel_table}.parquet")

    conn.create_arrow_table(node_table, nodes)
    conn.create_arrow_rel_table(
        rel_table,
        indices,
        src_table,
        dst_table,
        layout=lb.ArrowRelTableLayout.CSR,
        indptr_dataframe=indptr,
    )


def main() -> None:
    """Run the example."""
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--layout", choices=["flat", "csr"], default="csr")
    parser.add_argument("--node-table", required=True)
    parser.add_argument("--rel-table", required=True)
    parser.add_argument("--src-table")
    parser.add_argument("--dst-table")
    args = parser.parse_args()

    src_table = args.src_table or args.node_table
    dst_table = args.dst_table or args.node_table

    db = lb.Database(":memory:")
    conn = db.connect()
    if args.layout == "flat":
        register_flat(conn, args.data_dir, args.node_table, args.rel_table, src_table, dst_table)
    else:
        register_csr(conn, args.data_dir, args.node_table, args.rel_table, src_table, dst_table)

    result = conn.execute(f"MATCH (a:{src_table})-[r:{args.rel_table}]->(b:{dst_table}) RETURN COUNT(*)")
    print(result.get_next()[0])


if __name__ == "__main__":
    main()
