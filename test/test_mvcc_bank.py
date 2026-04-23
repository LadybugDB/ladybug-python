"""
Graph-based Jepsen Bank Test — MVCC anomaly detector.

A pytest port of adsharma/mvcc-bank (https://github.com/adsharma/mvcc-bank),
adapted to use ladybug directly and fit into the tools/python_api/test
pytest suite.

Anomalies checked
-----------------
  balance_conservation   sum(balance) must always equal the initial total
  negative_balance       no account may go below zero
  repeatable_read        two identical MATCH queries in the same READ ONLY txn
                         must return the same rows
  phantom_read           aggregate predicates (count, sum) must be stable
                         within the same READ ONLY txn

Run::

  cd tools/python_api
  pytest test/test_mvcc_bank.py -v

Or from the repo root::

  make pytest  (runs all Python API tests including this one)
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import ladybug as lb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N_ACCOUNTS = 10
INITIAL_BALANCE = 1000
TOTAL_MONEY = N_ACCOUNTS * INITIAL_BALANCE
EDGE_PROB = 0.5
MAX_TRANSFER = 100
RETRY_LIMIT = 10

# Short durations used in CI; increase manually for deeper stress testing.
DURATION_SINGLE_WRITER = 10  # seconds
DURATION_MULTI_WRITER = 15  # seconds


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def build_edges(n: int, prob: float, rng: random.Random) -> list[tuple[int, int]]:
    edges = []
    for i in range(n):
        for j in range(n):
            if i != j and rng.random() < prob:
                edges.append((i, j))
    # Guarantee connectivity: add a hub
    hub = n // 2
    for i in range(n):
        if i != hub and (hub, i) not in edges:
            edges.append((hub, i))
    return edges


def setup_db(db: lb.Database, n: int, edges: list[tuple[int, int]]) -> None:
    with lb.Connection(db) as conn:
        conn.execute(
            "CREATE NODE TABLE Account (id INT64, balance INT64, PRIMARY KEY (id))"
        )
        conn.execute("CREATE REL TABLE CanTransfer (FROM Account TO Account)")
        for i in range(n):
            conn.execute(f"CREATE (:Account {{id: {i}, balance: {INITIAL_BALANCE}}})")
        for src, dst in edges:
            conn.execute(
                f"MATCH (a:Account {{id: {src}}}), (b:Account {{id: {dst}}}) CREATE (a)-[:CanTransfer]->(b)"
            )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    """Counters and anomaly log shared across writer/reader threads."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    writes_committed: int = 0
    writes_skipped: int = 0
    write_conflicts: int = 0
    writes_failed: int = 0
    reads_ok: int = 0
    reads_failed: int = 0
    anomalies: list[str] = field(default_factory=list)

    def anomaly(self, kind: str, msg: str) -> None:
        with self._lock:
            self.anomalies.append(f"[{kind}] {msg}")

    def inc(self, counter: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, counter, getattr(self, counter) + n)


# ---------------------------------------------------------------------------
# Worker threads
# ---------------------------------------------------------------------------
def write_worker(
    db: lb.Database,
    edges: list[tuple[int, int]],
    stats: Stats,
    stop: threading.Event,
    rng: random.Random,
) -> None:
    conn = lb.Connection(db)
    while not stop.is_set():
        if not edges:
            break
        src, dst = rng.choice(edges)
        amount = rng.randint(1, MAX_TRANSFER)

        for attempt in range(RETRY_LIMIT):
            try:
                conn.execute("BEGIN TRANSACTION")
                row = conn.execute(
                    f"MATCH (a:Account {{id: {src}}}) RETURN a.balance"
                ).get_next()
                balance = row[0]
                if balance < amount:
                    conn.execute("ROLLBACK")
                    stats.inc("writes_skipped")
                    break
                conn.execute(
                    f"MATCH (a:Account {{id: {src}}}) SET a.balance = a.balance - {amount}"
                )
                conn.execute(
                    f"MATCH (b:Account {{id: {dst}}}) SET b.balance = b.balance + {amount}"
                )
                conn.execute("COMMIT")
                stats.inc("writes_committed")
                break
            except RuntimeError as exc:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    conn = lb.Connection(db)
                if "Write-write conflict" in str(exc):
                    stats.inc("write_conflicts")
                    if attempt == RETRY_LIMIT - 1:
                        stats.inc("writes_failed")
                else:
                    stats.inc("writes_failed")
                    break


def read_worker(
    db: lb.Database,
    stats: Stats,
    stop: threading.Event,
    total_money: int,
    n: int,
) -> None:
    conn = lb.Connection(db)
    tag = threading.current_thread().name
    while not stop.is_set():
        try:
            conn.execute("BEGIN TRANSACTION READ ONLY")

            # 1: balance conservation
            row = conn.execute("MATCH (a:Account) RETURN sum(a.balance)").get_next()
            total = row[0]
            if total != total_money:
                stats.anomaly(
                    "balance_conservation",
                    f"[{tag}] expected {total_money}, got {total}",
                )

            # 2: no negative balances
            neg = conn.execute(
                "MATCH (a:Account) WHERE a.balance < 0 RETURN count(a)"
            ).get_next()[0]
            if neg > 0:
                stats.anomaly(
                    "negative_balance",
                    f"[{tag}] {neg} accounts with negative balance",
                )

            # 3: repeatable read — same MATCH twice
            r1 = conn.execute("MATCH (a:Account) RETURN a.id, a.balance ORDER BY a.id")
            rows1 = []
            while r1.has_next():
                rows1.append(r1.get_next())
            r2 = conn.execute("MATCH (a:Account) RETURN a.id, a.balance ORDER BY a.id")
            rows2 = []
            while r2.has_next():
                rows2.append(r2.get_next())
            if rows1 != rows2:
                stats.anomaly(
                    "repeatable_read",
                    f"[{tag}] results diverged within same READ ONLY txn",
                )

            # 4: phantom read — aggregate must be stable
            agg1 = conn.execute(
                "MATCH (a:Account) RETURN count(a), sum(a.balance)"
            ).get_next()
            agg2 = conn.execute(
                "MATCH (a:Account) RETURN count(a), sum(a.balance)"
            ).get_next()
            if agg1 != agg2:
                stats.anomaly(
                    "phantom_read",
                    f"[{tag}] aggregate changed within one READ ONLY txn: {agg1} -> {agg2}",
                )

            conn.execute("COMMIT")
            stats.inc("reads_ok")
        except RuntimeError:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                conn = lb.Connection(db)
            stats.inc("reads_failed")


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------
def run_bank_test(
    db_path: Path,
    *,
    n_writers: int,
    n_readers: int,
    duration: int,
    enable_multi_writes: bool,
    seed: int = 42,
) -> Stats:
    rng = random.Random(seed)
    edges = build_edges(N_ACCOUNTS, EDGE_PROB, rng)

    try:
        db = lb.Database(str(db_path), enable_multi_writes=enable_multi_writes)
    except TypeError:
        # Fallback if binding patch is not applied
        db = lb.Database(str(db_path))

    setup_db(db, N_ACCOUNTS, edges)

    stats = Stats()
    stop = threading.Event()

    threads: list[threading.Thread] = []
    for i in range(n_writers):
        t = threading.Thread(
            target=write_worker,
            args=(db, edges, stats, stop, random.Random(seed + i + 1)),
            name=f"writer-{i}",
            daemon=True,
        )
        threads.append(t)
    for i in range(n_readers):
        t = threading.Thread(
            target=read_worker,
            args=(db, stats, stop, TOTAL_MONEY, N_ACCOUNTS),
            name=f"reader-{i}",
            daemon=True,
        )
        threads.append(t)

    for t in threads:
        t.start()
    time.sleep(duration)
    stop.set()
    for t in threads:
        t.join(timeout=10)

    return stats


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_single_writer_no_anomalies(tmp_path: Path) -> None:
    """Baseline: single writer, no concurrent write transactions."""
    stats = run_bank_test(
        tmp_path / "bank_single.lbdb",
        n_writers=1,
        n_readers=2,
        duration=DURATION_SINGLE_WRITER,
        enable_multi_writes=False,
    )
    assert stats.anomalies == [], f"MVCC anomalies detected: {stats.anomalies}"
    assert stats.reads_failed == 0, f"Reader errors: {stats.reads_failed}"


def test_multi_writer_no_anomalies(tmp_path: Path) -> None:
    """
    Four concurrent writers with enable_multi_writes=True.

    Write-write conflicts are expected and retried (OCC model); what must not
    happen is any MVCC anomaly visible to snapshot-isolated readers.
    """
    stats = run_bank_test(
        tmp_path / "bank_multi.lbdb",
        n_writers=4,
        n_readers=2,
        duration=DURATION_MULTI_WRITER,
        enable_multi_writes=True,
    )
    assert stats.anomalies == [], f"MVCC anomalies detected: {stats.anomalies}"
    assert stats.reads_failed == 0, f"Reader errors: {stats.reads_failed}"
    # Sanity: something actually ran
    assert stats.writes_committed > 0


@pytest.mark.slow
def test_multi_writer_stress_no_anomalies(tmp_path: Path) -> None:
    """
    Stress: 8 writers / 4 readers for 60 s (matches adsharma README example).

    Marked @pytest.mark.slow — skipped in fast CI runs unless -m slow is passed.
    """
    stats = run_bank_test(
        tmp_path / "bank_stress.lbdb",
        n_writers=8,
        n_readers=4,
        duration=60,
        enable_multi_writes=True,
    )
    assert stats.anomalies == [], f"MVCC anomalies detected: {stats.anomalies}"
