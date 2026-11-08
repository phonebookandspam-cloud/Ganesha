"""Loopback-only static non-wagering preview server; no wallet or wager API is enabled."""
import json
import os
import signal
import tempfile
from pathlib import Path
from ganesha.rgs.http_api import create_server
from ganesha.game.runtime import GameRuntime
from ganesha.demo.runtime_math import LocalRuntimeMathPort

HOST = "127.0.0.1"
PORT = int(os.environ.get("GANESHA_PORT", "8787"))
root = Path(__file__).resolve().parent
frontend = root / "frontend"
config_path = frontend / "config.js"
original_config = config_path.read_bytes() if config_path.exists() else None
server = None
runtime_db_path = os.environ.get("GANESHA_RUNTIME_DB")
owns_runtime_db = runtime_db_path is None
if owns_runtime_db:
    runtime_fd, runtime_db_path = tempfile.mkstemp(prefix="ganesha-runtime-preview-", suffix=".sqlite3")
    os.close(runtime_fd)
runtime = GameRuntime(LocalRuntimeMathPort(), storage_path=runtime_db_path)


def runtime_stop_provider(_session_id):
    # Server-owned deterministic vectors for local UI verification only.
    return [0, 0, 0, 0, 0], [[1, 1, 1, 1, 1] for _ in range(10)]


try:
    config_path.write_text("window.GANESHA_CONFIG = %s;\n" % json.dumps({
        "roundEndpoint": "http://127.0.0.1:%d" % PORT,
        "environment": "local-development",
        "providerConnected": False,
        "roundApiEnabled": False,
        "demoApiEnabled": True,
        "gameFixtureApiEnabled": True,
        "runtimeApiEnabled": True,
    }))
    server = create_server(HOST, PORT, frontend_root=frontend, enable_round_api=False,
                           enable_demo_api=True, enable_game_fixture_api=True,
                           runtime=runtime, runtime_stop_provider=runtime_stop_provider)
    print("Ganesha Full Scratch V1 static preview: http://%s:%d" % (HOST, PORT))
    print("Scripted demo, GameEngine fixture and independent non-financial runtime enabled; local Math is deterministic development-only; financial round API disabled")
    def _stop_on_signal(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, _stop_on_signal)
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    if server is not None:
        server.server_close()
    runtime.close()
    if owns_runtime_db:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(runtime_db_path + suffix).unlink()
            except FileNotFoundError:
                pass
    if original_config is None:
        try:
            config_path.unlink()
        except FileNotFoundError:
            pass
    else:
        config_path.write_bytes(original_config)
