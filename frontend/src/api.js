// Backend contract (implemented in backend/core/views.py + urls.py). All REST
// calls go through nginx's /api/ location (proxied to waitress); the
// websocket goes through /ws/ (proxied straight to workflow's ws_server,
// bypassing Django entirely).
//
//   POST /api/tasks/upload/            multipart file field "file" (.md)
//                                       -> 201 { task_spec_id }
//   POST /api/tasks/{id}/run/          body { stage: "extract"|"roster"|"negotiate"|"negotiate_step", ...extra }
//                                       - "negotiate" extra: { mode: "dev"|"prod", reset: bool }
//                                       - "negotiate_step" (dev mode only): advances a paused run by one step
//                                       -> 202 Accepted (fire-and-forget;
//                                          result arrives over the websocket)
//                                       -> 409 if the task isn't in the
//                                          status that stage requires
//   POST /api/tasks/{id}/verify/       flips status extracted -> verified
//                                       -> the full state (see below)
//   DELETE /api/tasks/{id}/            -> { deleted: true }
//                                       -> 409 if status="negotiating"
//   GET  /api/tasks/{id}/              -> full current state:
//     { task_spec_id, status, source_filename, extracted_json,
//       prime_overall_reasoning, roster: [...], resource_pools: [...],
//       negotiation_mode, negotiation_tree: [...] }
//     status is one of: pending | extracted | verified | roster_created |
//                        negotiating | done
//     negotiation_tree is a flat list of tree nodes:
//       { id, parent_id, role_name, model_tier, first_turn, entries: [...],
//         tool_results: [...] } -- entries accumulate on the same node when
//       the same role continues immediately (reflect/fact-resolution).
//
//   WS   /ws/tasks/{id}/               one JSON object per frame:
//     { type: "stage_started",  stage }
//     { type: "stage_complete", stage, ...stage-specific fields }
//       - stage "extract": { extracted_json }
//       - stage "roster":  { nodes, edges, roster, resource_pools, overall_reasoning }
//       - stage "negotiate"|"negotiate_step": { done, waiting_for_step }
//     { type: "stage_failed",   stage, error }
//     { type: "negotiate_node", event: "created", node }
//     { type: "negotiate_node", event: "continued"|"reflected", node_id, entry }
//     { type: "negotiate_node", event: "tool_results", node_id, tool_results }
//
//   GET  /api/tasks/{id}/sandbox/files/  -> { files: [relative/path, ...] }
//   GET  /api/tasks/{id}/sandbox/file/?path=... -> { path, content }
//   POST /api/tasks/{id}/sandbox/file/   body { path, content }
//                                         -> { path, written: true }
//                                         -> 409 unless status="negotiating"
//                                         (§8.3: inspect/edit sandbox state
//                                         while a dev-mode run is paused)

// --- disabled for read-only server deploy (uncomment locally) ---
// export async function uploadTaskFile(file) {
//   const form = new FormData();
//   form.append("file", file);
//   const res = await fetch("/api/tasks/upload/", { method: "POST", body: form });
//   if (!res.ok) throw new Error(`upload failed: ${res.status}`);
//   return res.json(); // { task_spec_id }
// }

async function postJson(url) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `${url} failed: ${res.status}`);
  return body;
}

export function runStage(taskSpecId, stage, extra = {}) {
  return fetch(`/api/tasks/${taskSpecId}/run/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stage, ...extra }),
  }).then(async (res) => {
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `run(${stage}) failed: ${res.status}`);
    return body;
  });
}

export function verifyTask(taskSpecId) {
  return postJson(`/api/tasks/${taskSpecId}/verify/`);
}

export async function fetchTasks() {
  const res = await fetch("/api/tasks/");
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `list tasks failed: ${res.status}`);
  return body.tasks;
}

export async function fetchTaskState(taskSpecId) {
  const res = await fetch(`/api/tasks/${taskSpecId}/`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `fetch task ${taskSpecId} failed: ${res.status}`);
  return body;
}

// --- disabled for read-only server deploy (uncomment locally) ---
// export async function deleteTask(taskSpecId) {
//   const res = await fetch(`/api/tasks/${taskSpecId}/`, { method: "DELETE" });
//   const body = await res.json().catch(() => ({}));
//   if (!res.ok) throw new Error(body.error || `delete task ${taskSpecId} failed: ${res.status}`);
//   return body;
// }

export function connectTaskSocket(taskSpecId, onMessage) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${window.location.host}/ws/tasks/${taskSpecId}/`);
  socket.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // ignore malformed frames
    }
  };
  return socket;
}

export async function fetchSandboxFiles(taskSpecId) {
  const res = await fetch(`/api/tasks/${taskSpecId}/sandbox/files/`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `list sandbox files failed: ${res.status}`);
  return body.files;
}

export async function fetchSandboxFile(taskSpecId, path) {
  const res = await fetch(`/api/tasks/${taskSpecId}/sandbox/file/?path=${encodeURIComponent(path)}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `read sandbox file failed: ${res.status}`);
  return body.content;
}

export async function writeSandboxFile(taskSpecId, path, content) {
  const res = await fetch(`/api/tasks/${taskSpecId}/sandbox/file/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `write sandbox file failed: ${res.status}`);
  return body;
}

// Builds the same {nodes, edges} shape the backend sends for stage_complete
// "roster", from a plain roster list -- used to render the graph identically
// whether we're resuming from GET state or reacting to a live websocket event.
export function buildRosterGraph(roster) {
  const nodes = [{ id: "Prime", label: "Prime" }, ...roster.map((r) => ({ id: r.role_name, label: r.role_name }))];
  const edges = roster.map((r) => ({ from: "Prime", to: r.role_name, label: r.model_tier }));
  return { nodes, edges };
}
