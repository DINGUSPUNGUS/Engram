#!/usr/bin/env python
"""M9 performance pass: measure real operations against a realistic synthetic
dataset before considering any optimization (per M9 scope: "identify actual
bottlenecks before changing implementation").

Builds one scratch space through the real CLI composition root
(``engram_cli.runtime.build_runtime``) -- the same code path a real user's
`engram` invocation runs, not a hand-rolled shortcut -- populates it with a
"thousands of events, not tiny fixtures" synthetic dataset matching the
scale architecture.md's own self-critique names ("At personal-memory scale
(thousands of events, not billions) replay cost is a non-issue for years"),
and times: event append, projection rebuild, differential-rebuild fidelity
verification, search (several query shapes), proposal merge/undo,
export/import, and dashboard API response times (via a real ASGI TestClient
against the same populated store).

Usage:  uv run --package engram-cli python scripts/benchmark_perf.py [--n 3000]

Writes results as JSON to evaluations/results/performance_baseline.json and
prints a human-readable table. Read-only with respect to the repo otherwise
-- everything happens in a temp directory that is cleaned up on exit.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


@contextmanager
def _timed(sink: list[float]) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        sink.append(time.perf_counter() - started)


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    n = len(ordered)
    p95_index = min(n - 1, round(0.95 * (n - 1)))
    return {
        "n": n,
        "total_s": round(sum(ordered), 4),
        "mean_ms": round(statistics.mean(ordered) * 1000, 4),
        "median_ms": round(statistics.median(ordered) * 1000, 4),
        "p95_ms": round(ordered[p95_index] * 1000, 4),
        "max_ms": round(ordered[-1] * 1000, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=3000, help="number of memories in the synthetic dataset"
    )
    args = parser.parse_args()
    n = args.n

    # ignore_cleanup_errors: SQLite on Windows can hold a file lock a beat
    # past engine.dispose() (WAL/journal sidecar files); that's a benchmark-
    # script artifact, not a defect in the code under measurement, and must
    # not discard results that already finished computing successfully.
    with tempfile.TemporaryDirectory(prefix="engram-bench-", ignore_cleanup_errors=True) as tmp:
        results = _run(Path(tmp), n)

        out_path = REPO_ROOT / "evaluations" / "results" / "performance_baseline.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n", encoding="utf-8")

        print(
            f"\n{'operation':<32} {'n':>6} {'total_s':>9} {'mean_ms':>9}"
            f" {'p95_ms':>9} {'max_ms':>9}"
        )
        print("-" * 80)
        for name, stat in results["operations"].items():
            print(
                f"{name:<32} {stat['n']:>6} {stat['total_s']:>9} {stat['mean_ms']:>9}"
                f" {stat['p95_ms']:>9} {stat['max_ms']:>9}"
            )
        print(f"\nwritten to {out_path.relative_to(REPO_ROOT)}")


def _run(data_dir: Path, n: int) -> dict[str, Any]:
    import random

    from engram_cli.config import CliSettings
    from engram_cli.runtime import build_runtime
    from engram_core.application.commands.drafts import EditMemoryDraft, to_dict
    from engram_core.application.dto import CreateMemoryInput
    from engram_core.domain.values import LinkRelation, MemoryKind
    from engram_events import Provenance
    from engram_storage_sqlite.migrate import upgrade_to_head

    db_path = data_dir / "engram.db"
    export_repo = data_dir / "memory"
    upgrade_to_head(db_path)
    settings = CliSettings(data_dir=data_dir, db_path=db_path, export_repo=export_repo)
    runtime = build_runtime(settings)

    user = Provenance(actor="user", detail="benchmark")
    rng = random.Random(42)
    tag_pool = [f"tag-{i}" for i in range(50)]

    operations: dict[str, dict[str, float]] = {}

    # -- event append: N single-event creates, then N small tag-update batches ---
    # One kind (fact) throughout -- the kind mix isn't the variable under
    # measurement here, and it keeps every create's attribute schema identical.
    create_times: list[float] = []
    ids = []
    for i in range(n):
        with _timed(create_times):
            memory_id = runtime.commands.create_memory(
                CreateMemoryInput(
                    kind=MemoryKind.FACT,
                    title=f"synthetic memory {i}",
                    content=f"content body for synthetic memory number {i} " * 3,
                    attributes={"statement": f"statement number {i}"},
                ),
                user,
            )
        ids.append(memory_id)
    operations["event_append_create"] = _stats(create_times)

    tag_times: list[float] = []
    for memory_id in ids:
        with _timed(tag_times):
            runtime.commands.tag_memory(
                memory_id, add=tuple(rng.sample(tag_pool, 2)), remove=(), provenance=user
            )
    operations["event_append_tag_update"] = _stats(tag_times)

    # A handful of links, spread across the dataset (graph reads exercise this).
    for i in range(0, n - 1, max(1, n // 200)):
        runtime.commands.link_memories(ids[i], ids[i + 1], LinkRelation.RELATES_TO, user)

    # -- projection rebuild: full replay of the log built above -------------------
    rebuild_times: list[float] = []
    with _timed(rebuild_times):
        runtime.rebuild()
    operations["projection_rebuild_full"] = _stats(rebuild_times)

    # -- status --verify: differential rebuild fidelity check ---------------------
    verify_times: list[float] = []
    with _timed(verify_times):
        runtime.verify_fidelity()
    operations["status_verify_differential_rebuild"] = _stats(verify_times)

    # -- search: several representative query shapes, repeated ---------------------
    queries = [
        "content",
        "kind:project",
        "confidence>0.5",
        f"tag:{tag_pool[0]}",
        "kind:fact content",
    ]
    search_times: list[float] = []
    for _ in range(20):
        for q in queries:
            with _timed(search_times):
                runtime.search.query(q, limit=20)
    operations["memory_search"] = _stats(search_times)

    # -- proposal open/merge/undo: a batch of real edit-intent proposals ----------
    proposal_sample = ids[: max(1, n // 20)]  # 5% of the dataset
    open_times: list[float] = []
    proposal_ids = []
    for memory_id in proposal_sample:
        memory = runtime.queries.get_memory(memory_id)
        draft = to_dict(
            EditMemoryDraft(
                memory_id=memory_id,
                base_version=memory.version,
                title=f"{memory.title} (edited)",
            )
        )
        with _timed(open_times):
            proposal_id = runtime.proposals.open_proposal(
                "benchmark edit", "synthetic edit for perf measurement", [draft], user
            )
        runtime.proposals.approve_proposal(proposal_id, "ok", user)
        proposal_ids.append(proposal_id)
    operations["proposal_open"] = _stats(open_times)

    merge_times: list[float] = []
    for proposal_id in proposal_ids:
        with _timed(merge_times):
            runtime.proposals.merge_proposal(proposal_id, user)
    operations["proposal_merge"] = _stats(merge_times)

    undo_times: list[float] = []
    for proposal_id in proposal_ids:
        with _timed(undo_times):
            runtime.proposals.undo_proposal(proposal_id, "benchmark undo", user)
    operations["proposal_undo"] = _stats(undo_times)

    # -- export / import -----------------------------------------------------------
    export_times: list[float] = []
    with _timed(export_times):
        runtime.exporter.export(export_repo)
    operations["export_full"] = _stats(export_times)

    restore_dir = data_dir / "restored"
    restore_db = restore_dir / "engram.db"
    upgrade_to_head(restore_db)
    restore_settings = CliSettings(
        data_dir=restore_dir, db_path=restore_db, export_repo=export_repo
    )
    restore_runtime = build_runtime(restore_settings)
    import_times: list[float] = []
    with _timed(import_times):
        restore_runtime.importer.restore(export_repo)
    operations["import_restore"] = _stats(import_times)

    # -- dashboard API response times: real ASGI app, real TestClient -------------
    dashboard_times = _measure_dashboard(data_dir, ids[:20])
    operations.update(dashboard_times)

    runtime.engine.dispose()
    restore_runtime.engine.dispose()

    return {
        "dataset": {
            "memories": n,
            "tag_updates": n,
            "links": len(range(0, n - 1, max(1, n // 200))),
            "proposals_merged_then_undone": len(proposal_ids),
        },
        "operations": operations,
    }


def _measure_dashboard(data_dir: Path, sample_ids: list[Any]) -> dict[str, dict[str, float]]:
    from fastapi.testclient import TestClient

    from engram_api.config import EngramSettings
    from engram_api.main import create_app

    settings = EngramSettings(data_dir=data_dir, env="test")
    app = create_app(settings)
    results: dict[str, dict[str, float]] = {}
    with TestClient(app) as client:
        list_times: list[float] = []
        for _ in range(20):
            with _timed(list_times):
                resp = client.get("/api/v1/memories", params={"limit": 20})
            assert resp.status_code == 200, resp.text
        results["dashboard_api_list_memories"] = _stats(list_times)

        detail_times: list[float] = []
        for memory_id in sample_ids:
            with _timed(detail_times):
                resp = client.get(f"/api/v1/memories/{memory_id}")
            assert resp.status_code == 200, resp.text
        results["dashboard_api_get_memory"] = _stats(detail_times)

        stats_times: list[float] = []
        for _ in range(20):
            with _timed(stats_times):
                resp = client.get("/api/v1/stats")
            assert resp.status_code == 200, resp.text
        results["dashboard_api_stats"] = _stats(stats_times)

        search_times: list[float] = []
        for _ in range(20):
            with _timed(search_times):
                resp = client.get("/api/v1/search", params={"q": "content", "limit": 20})
            assert resp.status_code == 200, resp.text
        results["dashboard_api_search"] = _stats(search_times)
    return results


if __name__ == "__main__":
    main()
