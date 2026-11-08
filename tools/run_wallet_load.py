"""Local SQLite WalletLedger concurrency smoke; never uses real funds or canonical Math."""
import argparse
import hashlib
import json
import statistics
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ganesha.wallet.ledger import WalletLedger

ROOT = Path(__file__).resolve().parents[1]


def run(workers=12, rounds_per_worker=20):
    if type(workers) is not int or not 1 <= workers <= 64:
        raise ValueError("workers must be an integer in [1, 64]")
    if type(rounds_per_worker) is not int or not 1 <= rounds_per_worker <= 1000:
        raise ValueError("rounds_per_worker must be an integer in [1, 1000]")
    with tempfile.TemporaryDirectory(prefix="ganesha-wallet-load-") as tmp:
        ledger = WalletLedger(Path(tmp) / "wallet.sqlite3")
        opening = workers * rounds_per_worker * 100 + 1000
        ledger.create_account("load-test-account", "USD", opening)
        latencies = []
        errors = []
        def worker(worker_id):
            samples = []
            for index in range(rounds_per_worker):
                round_id = f"load:{worker_id}:{index}"
                start = time.perf_counter()
                phase = "reserve_bet"
                try:
                    ledger.reserve_bet(
                        f"debit:{round_id}", round_id, "load-test-account", 100,
                        rng_commitment="TEST:LOCAL-LOAD-ONLY", max_payout_minor=1000,
                        round_mode="BASE", base_bet_minor=100,
                        generator_version="load-test-only", engine_version="load-test-only",
                    )
                    phase = "claim_recovery_lease"
                    token = ledger.claim_recovery_lease(round_id, f"worker-{worker_id}", lease_seconds=30)
                    phase = "commit_outcome"
                    ledger.commit_outcome(round_id, {
                        "mode": "BASE", "test_only": True, "total_payout_milli": 1000,
                    }, 100, token)
                    phase = "settle_round"
                    ledger.settle_round(f"settle:{round_id}", round_id, token)
                    phase = "release_recovery_lease"
                    ledger.release_recovery_lease(round_id, f"worker-{worker_id}", token)
                    samples.append((time.perf_counter() - start) * 1000)
                except Exception as exc:
                    errors.append({"round_id": round_id, "phase": phase, "error": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
            return samples

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(worker, worker_id) for worker_id in range(workers)]
            for future in as_completed(futures):
                latencies.extend(future.result())
        elapsed = time.perf_counter() - started
        final = ledger.balance("load-test-account")
        pending = ledger.pending_round_ids()
        snapshots_ok = not errors and len(latencies) == workers * rounds_per_worker
        if snapshots_ok:
            for worker_id in range(workers):
                for index in range(rounds_per_worker):
                    round_id = f"load:{worker_id}:{index}"
                    snapshot = ledger.round_snapshot(round_id)
                    replayed = ledger.round_state(round_id)
                    if (snapshot["round"]["status"] != "SETTLED"
                            or replayed["status"] != "ENDED" or replayed["ended"] is not True):
                        snapshots_ok = False
        expected = workers * rounds_per_worker
        source_hashes = {
            "src/ganesha/wallet/ledger.py": hashlib.sha256((ROOT / "src/ganesha/wallet/ledger.py").read_bytes()).hexdigest(),
            "tools/run_wallet_load.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        result = {
            "schema": "ganesha-local-wallet-load.v1",
            "source_sha256": source_hashes,
            "status": "PASS_LOCAL_SQLITE_ONLY" if not errors and len(latencies) == expected and not pending and snapshots_ok and final["balance_minor"] == opening else "FAIL",
            "real_funds": False,
            "canonical_math": False,
            "distributed_exactly_once_claim": False,
            "database": "temporary local SQLite WAL; removed after run",
            "workers": workers,
            "rounds_per_worker": rounds_per_worker,
            "rounds_expected": expected,
            "rounds_settled": len(latencies),
            "elapsed_seconds": round(elapsed, 4),
            "throughput_rounds_per_second": round(len(latencies) / elapsed, 2) if elapsed else 0,
            "sqlite_busy_timeout_ms": 250,
            "begin_immediate_retry_timeout_seconds": 30,
            "sqlite_write_lock_retry_count": ledger.write_lock_retry_count,
            "latency_ms": {
                "p50": round(statistics.median(latencies), 3) if latencies else None,
                "p95": round(sorted(latencies)[min(len(latencies)-1, int(len(latencies)*0.95))], 3) if latencies else None,
                "max": round(max(latencies), 3) if latencies else None,
            },
            "opening_balance_minor": opening,
            "final_balance_minor": final["balance_minor"],
            "pending_rounds": pending,
            "all_rounds_replay_terminal": snapshots_ok,
            "errors": errors,
            "scope": "Concurrency and replay smoke of local SQLite WalletLedger only. No production Provider, distributed deployment, canonical Math, latency SLO or release-load acceptance threshold is tested.",
        }
    output = ROOT / "artifacts/LOCAL_WALLET_LOAD_20261104.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "PASS_LOCAL_SQLITE_ONLY":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--rounds-per-worker", type=int, default=20)
    args = parser.parse_args()
    run(args.workers, args.rounds_per_worker)
