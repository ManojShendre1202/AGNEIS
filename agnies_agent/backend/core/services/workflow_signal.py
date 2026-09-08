"""Sends the fire-and-forget TCP signal to the workflow worker process
(agnies_agent/workflow/tcp_server.py). Connects, sends one JSON line, closes
-- does not wait for the pipeline stage to actually run or finish.
"""

import json
import socket

WORKFLOW_HOST = "127.0.0.1"
WORKFLOW_PORT = 8765
CONNECT_TIMEOUT_SECONDS = 3


class WorkflowUnavailable(Exception):
    pass


def send_stage_signal(stage: str, task_spec_id: int, **extra) -> None:
    """extra is forwarded as extra kwargs to the stage handler (e.g. negotiate's
    mode="dev"|"prod", reset=bool) -- see workflow/tcp_server.py::_handle_connection."""
    payload = json.dumps({"stage": stage, "task_spec_id": task_spec_id, **extra}).encode("utf-8")
    try:
        with socket.create_connection(
            (WORKFLOW_HOST, WORKFLOW_PORT), timeout=CONNECT_TIMEOUT_SECONDS
        ) as sock:
            sock.sendall(payload)
    except OSError as e:
        raise WorkflowUnavailable(
            f"could not reach workflow worker at {WORKFLOW_HOST}:{WORKFLOW_PORT} -- "
            f"is 'python -m workflow.main' running? ({e})"
        ) from e
