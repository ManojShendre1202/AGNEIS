"""Websocket server -- the workflow worker talks directly to the frontend
here, bypassing Django entirely. Browsers connect to /ws/tasks/<id>/ (nginx
proxies the whole path straight through to this server, see
C:\\nginx\\conf\\nginx.conf); tcp_server.py's job runner calls publish() from
a worker thread once a stage starts/finishes to broadcast the result to every
browser subscribed to that task_spec_id.
"""

import asyncio
import json
import re
import threading

import websockets

HOST = "127.0.0.1"
PORT = 8061  # proxied by nginx at :8050/ws/

_PATH_RE = re.compile(r"/ws/tasks/(\d+)/?$")

_subscribers: dict[int, set] = {}
_loop: asyncio.AbstractEventLoop | None = None
_loop_ready = threading.Event()


async def _handler(websocket) -> None:
    match = _PATH_RE.search(websocket.request.path)
    if not match:
        await websocket.close(code=4000, reason="expected /ws/tasks/<id>/")
        return
    task_spec_id = int(match.group(1))
    _subscribers.setdefault(task_spec_id, set()).add(websocket)
    try:
        async for _ in websocket:
            pass  # no messages expected from the browser on this channel
    finally:
        _subscribers[task_spec_id].discard(websocket)


async def _broadcast(task_spec_id: int, message: dict) -> None:
    sockets = list(_subscribers.get(task_spec_id, ()))
    if not sockets:
        return
    payload = json.dumps(message)
    for ws in sockets:
        try:
            await ws.send(payload)
        except Exception:
            _subscribers[task_spec_id].discard(ws)


def publish(task_spec_id: int, message: dict) -> None:
    """Thread-safe: called from tcp_server.py's worker-pool threads, not the
    asyncio event loop thread."""
    _loop_ready.wait(timeout=5)
    if _loop is None:
        print(f"[workflow] ws_server loop not ready, dropping message for task_spec_id={task_spec_id}")
        return
    asyncio.run_coroutine_threadsafe(_broadcast(task_spec_id, message), _loop)


async def _serve() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    _loop_ready.set()
    async with websockets.serve(_handler, HOST, PORT):
        print(f"[workflow] websocket server listening on {HOST}:{PORT}")
        await asyncio.Future()  # run forever


def serve_forever() -> None:
    asyncio.run(_serve())
