"""Concurrent local SQLite load for GuardedWalletLedger and its v2 evidence chain."""
import hashlib
import json
import statistics
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ganesha.demo.game_fixture import PresentationFixtureMathPort
from ganesha.game.engine import GameEngine
from ganesha.rgs.standard_startup_v1 import create_guarded_round_service
from ganesha.math.rng import HmacStopGenerator
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import GuardedWalletLedger

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/LOCAL_WALLET_V2_LOAD_20261105_R6.json"


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def run(workers=24, rounds_per_worker=50):
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError("workers must be an exact integer in [1, 32]")
    if type(rounds_per_worker) is not int or not 1 <= rounds_per_worker <= 100:
        raise ValueError("rounds_per_worker must be an exact integer in [1, 100]")
    if OUTPUT.exists():
        raise FileExistsError("refusing to overwrite existing evidence: %s" % OUTPUT)

    with tempfile.TemporaryDirectory(prefix="ganesha-wallet-v2-load-") as directory:
        ledger = WalletLedger(Path(directory) / "wallet.sqlite3")
        total = workers * rounds_per_worker
        opening = total * 100 + 1_000
        ledger.create_account("v2-load-account", "USD", opening)
        service = create_guarded_round_service(
            ledger,
            stop_generator=HmacStopGenerator(b"ganesha-v2-load-r6-key-000000000000"),
            game_engine=GameEngine(PresentationFixtureMathPort()),
            test_mode=True,
            allow_test_vectors=True,
        )
        guarded = service.ledger
        if not isinstance(guarded, GuardedWalletLedger):
            raise AssertionError("standard startup did not inject GuardedWalletLedger")
        vectors = [(0, 0, 0, 0, 0)] * 11
        errors = []
        latencies = []

        def worker(worker_id):
            completed = []
            for index in range(rounds_per_worker):
                round_id = "v2load:%d:%d" % (worker_id, index)
                started = time.perf_counter()
                phase = "play_round"
                try:
                    result = service.play_round(
                        "v2-load-account", round_id, "v2loadop:%d:%d" % (worker_id, index),
                        100, "BASE", internal_stop_vectors=vectors,
                    )
                    phase = "v1_reconcile"
                    if result["state"]["status"] != "ENDED":
                        raise AssertionError("round state did not reach ENDED")
                    if not ledger.reconcile_round(round_id)["ok"]:
                        raise AssertionError("v1 Wallet reconciliation failed")
                    phase = "v2_verify"
                    evidence = guarded.financial_evidence_v2(round_id)
                    public = guarded.public_financial_evidence_v2(round_id)
                    if len(evidence) != 11 or len(public) != 11:
                        raise AssertionError("v2 evidence stream does not contain BASE + ten FEATURE events")
                    if result["settlement"]["payout_minor"] != 150:
                        raise AssertionError("unexpected fixture payout conversion")
                    completed.append((time.perf_counter() - started) * 1000)
                except Exception as exc:
                    errors.append({
                        "round_id": round_id, "phase": phase,
                        "error": type(exc).__name__, "message": str(exc),
                        "traceback": traceback.format_exc(),
                    })
            return completed

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(worker, worker_id) for worker_id in range(workers)]
            for future in as_completed(futures):
                latencies.extend(future.result())
        elapsed = time.perf_counter() - started
        final = ledger.balance("v2-load-account")
        pending = ledger.pending_round_ids()
        expected_final = opening + total * 50
        all_terminal = len(latencies) == total and not pending and not errors
        result = {
            "schema": "ganesha-local-wallet-v2-load.v1",
            "status": "PASS_LOCAL_SQLITE_ONLY" if all_terminal and final["balance_minor"] == expected_final else "FAIL",
            "workers": workers,
            "rounds_per_worker": rounds_per_worker,
            "rounds_expected": total,
            "rounds_settled_and_v1_v2_verified": len(latencies),
            "elapsed_seconds": round(elapsed, 4),
            "throughput_rounds_per_second": round(len(latencies) / elapsed, 2) if elapsed else 0,
            "latency_ms": {
                "p50": round(statistics.median(latencies), 3) if latencies else None,
                "p95": round(sorted(latencies)[min(len(latencies) - 1, int(len(latencies) * 0.95))], 3) if latencies else None,
                "max": round(max(latencies), 3) if latencies else None,
            },
            "sqlite_write_lock_retry_count": ledger.write_lock_retry_count,
            "opening_balance_minor": opening,
            "final_balance_minor": final["balance_minor"],
            "expected_final_balance_minor": expected_final,
            "pending_rounds": pending,
            "all_rounds_terminal_and_v1_v2_verified": all_terminal,
            "errors": errors,
            "real_funds": False,
            "canonical_math": False,
            "distributed_multi_host": False,
            "production_wallet_claim": False,
            "database": "temporary local SQLite; deleted after run",
            "source_sha256": {
                path: sha(path) for path in (
                    "src/ganesha/rgs/standard_startup_v1.py",
                    "src/ganesha/rgs/service.py",
                    "src/ganesha/game/engine.py",
                    "src/ganesha/game/engine_payout_guard_r1.py",
                    "src/ganesha/demo/game_fixture.py",
                    "src/ganesha/math/config.py",
                    "src/ganesha/math/rng.py",
                    "src/ganesha/wallet/ledger.py",
                    "src/ganesha/wallet/financial_evidence_contract_v2.py",
                    "src/ganesha/wallet/settlement_boundary_v2_r2.py",
                    "tools/run_wallet_v2_load_r6.py",
                )
            },
            "scope": "Concurrent local SQLite integration load through create_guarded_round_service: GuardedGameEngine + GuardedWalletLedger + v1 Wallet journal + v2 linked evidence sidecar. Explicit test_mode with non-financial fixture Math; not canonical, distributed, production or Provider.",
        }

    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "PASS_LOCAL_SQLITE_ONLY":
        raise SystemExit(1)


if __name__ == "__main__":
    run()
