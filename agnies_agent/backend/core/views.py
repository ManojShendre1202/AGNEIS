import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from backend.agnies.negotiation.executor import (
    SandboxViolation,
    snapshot_existing_files,
    resolve_sandbox_path,
)
from backend.core.services.task_spec_service import TaskSpecService
from backend.core.services.workflow_signal import WorkflowUnavailable, send_stage_signal

# Keep in sync with agnies_agent/workflow/pipeline_config.py's STAGE_HANDLERS
# keys.
#
# Each stage lists every status it's allowed to run FROM -- not just the
# status right before it, but also its own completed status, so a stage can
# be re-run in place (e.g. to pick up a prompt change) without re-uploading
# and creating a new task_spec_id. Handlers replace their own prior output
# rather than appending to it (see run_extract/run_roster/run_negotiate).
#
# "negotiate" accepts body fields {mode: "dev"|"prod", reset: bool} which
# run_stage_view forwards straight through to run_negotiate as kwargs.
# "negotiate_step" only ever applies to a dev-mode run currently paused
# mid-negotiation, hence the single allowed status.
STAGE_ALLOWED_STATUSES = {
    "extract": {"pending", "extracted", "verified", "roster_created"},
    "roster": {"verified", "roster_created"},
    "negotiate": {"roster_created", "negotiating", "done"},
    "negotiate_step": {"negotiating"},
}


# --- disabled for read-only server deploy (uncomment locally) ---
# @csrf_exempt
# @require_POST
# def upload_task_view(request):
#     uploaded = request.FILES.get("file")
#     if uploaded is None:
#         return JsonResponse({"error": "missing 'file'"}, status=400)
#     raw_text = uploaded.read().decode("utf-8", errors="replace")
#     task_spec = TaskSpecService.create_from_upload(uploaded.name, raw_text)
#     return JsonResponse({"task_spec_id": task_spec.id}, status=201)


@csrf_exempt
@require_POST
def run_stage_view(request, task_spec_id: int):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    stage = body.get("stage")
    if stage not in STAGE_ALLOWED_STATUSES:
        return JsonResponse(
            {"error": f"stage must be one of {sorted(STAGE_ALLOWED_STATUSES)}"}, status=400
        )

    if not TaskSpecService.exists(task_spec_id):
        return JsonResponse({"error": f"no task_spec_id={task_spec_id}"}, status=404)

    current_status = TaskSpecService.get(task_spec_id).status
    allowed_statuses = STAGE_ALLOWED_STATUSES[stage]
    if current_status not in allowed_statuses:
        return JsonResponse(
            {
                "error": f"stage={stage!r} requires status in {sorted(allowed_statuses)}, "
                f"but task_spec_id={task_spec_id} is currently {current_status!r}"
            },
            status=409,
        )

    extra = {k: v for k, v in body.items() if k != "stage"}
    try:
        send_stage_signal(stage, task_spec_id, **extra)
    except WorkflowUnavailable as e:
        return JsonResponse({"error": str(e)}, status=503)

    return JsonResponse({"accepted": True}, status=202)


@csrf_exempt
@require_POST
def verify_task_view(request, task_spec_id: int):
    if not TaskSpecService.exists(task_spec_id):
        return JsonResponse({"error": f"no task_spec_id={task_spec_id}"}, status=404)

    current_status = TaskSpecService.get(task_spec_id).status
    if current_status != "extracted":
        return JsonResponse(
            {"error": f"can only verify from status='extracted', currently {current_status!r}"},
            status=409,
        )

    TaskSpecService.mark_verified(task_spec_id)
    return JsonResponse(TaskSpecService.get_state(task_spec_id))


@require_GET
def tasks_list_view(request):
    tasks = TaskSpecService.list_all()
    return JsonResponse({"tasks": tasks})


@csrf_exempt
def task_state_view(request, task_spec_id: int):
    if not TaskSpecService.exists(task_spec_id):
        return JsonResponse({"error": f"no task_spec_id={task_spec_id}"}, status=404)

    if request.method == "GET":
        return JsonResponse(TaskSpecService.get_state(task_spec_id))

    # --- disabled for read-only server deploy (uncomment locally) ---
    # if request.method == "DELETE":
    #     # Deliberately allowed even mid-negotiation: if that task's run is
    #     # still live in negotiation_graph.py's in-process _RUNS dict, its
    #     # next negotiate_step will hit a real FK error trying to write a
    #     # NegotiationTurn/etc. row against a task_spec_id that no longer
    #     # exists -- acceptable, the user asked to be able to force this.
    #     TaskSpecService.delete(task_spec_id)
    #     return JsonResponse({"deleted": True})

    return JsonResponse({"error": "method not allowed"}, status=405)


# --- Sandbox file browser/editor (§8.3: inspect/edit sandbox state while a
# dev-mode negotiation run is paused between steps). Listing/reading a
# file's content is allowed at any status -- it's just showing what's on
# disk, same ground truth list_sandbox_files already backs internally
# (snapshot_existing_files, per-turn role prompt context). Writing is
# restricted to status="negotiating", the same single status
# "negotiate_step" itself is gated to, since editing sandbox state only
# makes sense as a human intervening in a currently-paused run, not before
# a run exists or after it's already been marked done.

_MAX_SANDBOX_FILE_READ_BYTES = 512_000


@require_GET
def sandbox_files_view(request, task_spec_id: int):
    if not TaskSpecService.exists(task_spec_id):
        return JsonResponse({"error": f"no task_spec_id={task_spec_id}"}, status=404)
    return JsonResponse({"files": snapshot_existing_files(task_spec_id)})


@csrf_exempt
def sandbox_file_view(request, task_spec_id: int):
    if not TaskSpecService.exists(task_spec_id):
        return JsonResponse({"error": f"no task_spec_id={task_spec_id}"}, status=404)

    if request.method == "GET":
        relative_path = request.GET.get("path")
        if not relative_path:
            return JsonResponse({"error": "missing 'path' query param"}, status=400)
        try:
            resolved = resolve_sandbox_path(task_spec_id, relative_path)
        except SandboxViolation as e:
            return JsonResponse({"error": str(e)}, status=400)
        if not resolved.is_file():
            return JsonResponse({"error": f"no such file: {relative_path!r}"}, status=404)
        if resolved.stat().st_size > _MAX_SANDBOX_FILE_READ_BYTES:
            return JsonResponse({"error": "file too large to view in the browser"}, status=413)
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return JsonResponse({"path": relative_path, "content": content})

    if request.method == "POST":
        current_status = TaskSpecService.get(task_spec_id).status
        if current_status != "negotiating":
            return JsonResponse(
                {"error": f"can only edit sandbox files while status='negotiating', "
                          f"currently {current_status!r}"},
                status=409,
            )
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid JSON body"}, status=400)
        relative_path = body.get("path")
        content = body.get("content")
        if not relative_path or content is None:
            return JsonResponse({"error": "body must include 'path' and 'content'"}, status=400)
        try:
            resolved = resolve_sandbox_path(task_spec_id, relative_path)
        except SandboxViolation as e:
            return JsonResponse({"error": str(e)}, status=400)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return JsonResponse({"path": relative_path, "written": True})

    return JsonResponse({"error": "method not allowed"}, status=405)
