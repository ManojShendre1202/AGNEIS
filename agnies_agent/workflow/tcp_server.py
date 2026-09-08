"""TCP listener the workflow worker process uses to receive fire-and-forget
run signals from Django (backend/core, via views.py once that's built).

Protocol: a single JSON line per connection --
    {"stage": "extract" | "roster" | "negotiate" | "negotiate_step",
     "task_spec_id": <int>, ...extra}
Django connects, sends that payload, and closes without waiting for a
response -- true fire-and-forget. Any fields beyond stage/task_spec_id (e.g.
negotiate's mode="dev"|"prod", reset=bool) are forwarded as kwargs straight
to the resolved handler. The stage job itself is handed to a small thread
pool here so multiple task_spec_id runs can proceed concurrently instead of
queuing behind one long negotiation run.
"""

import importlib
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

from workflow import ws_server
from workflow.pipeline_config import STAGE_HANDLERS

HOST = "127.0.0.1"
PORT = 8765
MAX_WORKERS = 4

_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def _resolve_handler(stage: str):
    if stage not in STAGE_HANDLERS:
        raise ValueError(f"Unknown stage {stage!r} -- must be one of {list(STAGE_HANDLERS)}")
    module_path, func_name = STAGE_HANDLERS[stage].split(":")
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def _run_job(stage: str, task_spec_id: int, **kwargs) -> None:
    print(f"[workflow] running stage={stage!r} task_spec_id={task_spec_id} kwargs={kwargs}")
    ws_server.publish(task_spec_id, {"type": "stage_started", "stage": stage})
    try:
        handler = _resolve_handler(stage)
        result = handler(task_spec_id, **kwargs) or {}
        print(f"[workflow] stage={stage!r} task_spec_id={task_spec_id} finished")
        ws_server.publish(task_spec_id, {"type": "stage_complete", "stage": stage, **result})
    except Exception as e:
        print(f"[workflow] stage={stage!r} task_spec_id={task_spec_id} FAILED: {e!r}")
        ws_server.publish(task_spec_id, {"type": "stage_failed", "stage": stage, "error": str(e)})


def _handle_connection(conn: socket.socket, addr) -> None:
    with conn:
        data = conn.recv(4096)
    if not data:
        return
    try:
        payload = json.loads(data.decode("utf-8"))
        stage = payload["stage"]
        task_spec_id = int(payload["task_spec_id"])
        kwargs = {k: v for k, v in payload.items() if k not in ("stage", "task_spec_id")}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        print(f"[workflow] bad signal from {addr}: {e!r}")
        return
    _pool.submit(_run_job, stage, task_spec_id, **kwargs)


def serve_forever() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        print(f"[workflow] TCP listener on {HOST}:{PORT}")
        while True:
            conn, addr = server.accept()
            threading.Thread(target=_handle_connection, args=(conn, addr), daemon=True).start()
