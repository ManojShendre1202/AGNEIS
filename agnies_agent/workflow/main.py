"""Entry point for the workflow worker process -- the homemade worker pool
that runs the AGNIES pipeline stages, separate from the Django/Waitress
process.

Run as (from agnies_agent/, so 'workflow' resolves as a top-level package
sibling to backend/):

    python -m workflow.main

Starts two things concurrently:
  - the TCP listener (tcp_server.py), which receives fire-and-forget stage
    signals from Django and dispatches them via pipeline_config.STAGE_HANDLERS
  - the websocket stub (ws_server.py), reserved for direct worker/frontend
    communication later
"""

import os
import threading

import django

# The workflow worker is a separate process from Django/waitress -- it needs
# its own django.setup() before any stage handler (extract/roster/negotiate)
# can touch backend.core.models / the service layer.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from workflow import tcp_server, ws_server  # noqa: E402 -- must follow django.setup()


def main() -> None:
    ws_thread = threading.Thread(target=ws_server.serve_forever, daemon=True)
    ws_thread.start()

    tcp_server.serve_forever()  # blocks


if __name__ == "__main__":
    main()
