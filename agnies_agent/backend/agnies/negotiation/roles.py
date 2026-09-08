"""One role's LLM turn, and actually executing the TOOL_USE calls it made."""

from .agent_shell import (
    build_prompt_tiers,
    format_interface_contracts,
    format_pending_asks,
    format_resolved_facts,
    format_role_activity,
    format_roster_list,
    format_sandbox_files,
    format_stack_decisions,
    invoke_role_turn,
    load_interface_contracts,
    load_resolved_facts,
    load_role,
    load_role_activity,
    load_stack_decisions,
    save_interface_contract,
    save_role_activity,
    save_stack_decision,
)
from .executor import (
    execute_edit_file,
    execute_install_package,
    execute_list_dir,
    execute_read_file,
    execute_run_shell,
    execute_write_file,
    snapshot_existing_files,
)
from .ownership import check_and_claim_ownership, check_read_allowed

def run_role(task_spec_id: int, task_spec: dict, roster: list[dict], api_key: str,
             role_name: str, instruction: str, conversation: str, turn: int,
             pending_asks: list[dict] | None = None,
             tool_results_text: str | None = None,
             open_tool_errors: dict[str, str] | None = None) -> dict:

    role = load_role(task_spec_id, role_name)

    roster_list_text = format_roster_list(roster, role_name)

    pending_asks_text = format_pending_asks(pending_asks or [])

    resolved_facts_text = format_resolved_facts(load_resolved_facts(task_spec_id))

    stack_decisions_text = format_stack_decisions(load_stack_decisions(task_spec_id))

    role_activity_text = format_role_activity(load_role_activity(task_spec_id, role_name))

    sandbox_files_text = format_sandbox_files(snapshot_existing_files(task_spec_id))

    interface_contracts_text = format_interface_contracts(load_interface_contracts(task_spec_id))

    static_prompt, dynamic_prompt = build_prompt_tiers(
        role, roster_list_text, resolved_facts_text, task_spec,
        conversation=conversation, instruction=instruction,
        sandbox_files_text=sandbox_files_text,
        stack_decisions_text=stack_decisions_text,
        role_activity_text=role_activity_text,
        pending_asks_text=pending_asks_text,
        tool_results_text=tool_results_text or "(nothing ran since your last turn)",
        open_errors_text=format_open_errors(open_tool_errors or {}),
        interface_contracts_text=interface_contracts_text,
    )
    label = f"{role_name} role_turn LLM call"

    turn_result, usage = invoke_role_turn(role["model_tier"], static_prompt, dynamic_prompt, label=label)

    existing_packages = {d["package"].lower() for d in load_stack_decisions(task_spec_id)}
    new_stack_decisions = []
    for decision in turn_result.stack_decisions:
        if decision.package.lower() in existing_packages:
            continue
        save_stack_decision(task_spec_id, role_name, decision.package, version=None,
                             reasoning=decision.reasoning)
        new_stack_decisions.append({"package": decision.package, "reasoning": decision.reasoning})
        existing_packages.add(decision.package.lower())

    existing_signatures = {
        c["function_name"].lower(): c["signature"] for c in load_interface_contracts(task_spec_id)
    }
    new_interface_contracts = []
    for contract in turn_result.publishes_interfaces:
        key = contract.function_name.lower()
        if existing_signatures.get(key) == contract.signature:
            continue
        save_interface_contract(task_spec_id, role_name, contract.path, contract.function_name,
                                 contract.signature, contract.description)
        new_interface_contracts.append({
            "path": contract.path, "function_name": contract.function_name,
            "signature": contract.signature, "description": contract.description,
        })
        existing_signatures[key] = contract.signature

    return {
        "role_name": role_name,
        "model_tier": role["model_tier"],
        "response": turn_result.response,
        "history_note": turn_result.history_note,
        "tool_use": [
            {"tool": t.tool, "why": t.why, "path": t.path, "command": t.command, "packages": t.packages}
            for t in turn_result.tool_calls
        ],
        "requests_to_prime": [{"what": r.what, "why": r.why} for r in turn_result.requests_to_prime],
        "addressed_to": [{"role": a.role, "ask": a.ask} for a in turn_result.addressed_to],
        "stack_decisions": new_stack_decisions,
        "interface_contracts": new_interface_contracts,
        "usage": usage,
    }


_HISTORY_FALLBACK_CHARS = 200


def conversation_entry_text(result: dict) -> str | None:
    """What a turn contributes to the permanent conversation log -- normally
    the model's own `history_note` (short, by instruction). Falls back to a
    hard-capped slice of `response` only if the model left history_note empty
    despite taking real action (tool_calls/addressed_to/requests_to_prime),
    so a model lapse can't silently erase a turn that did something; a truly
    empty turn (nothing happened) contributes nothing, same as an explicit
    empty history_note."""
    note = (result.get("history_note") or "").strip()
    if note:
        return note
    took_action = result.get("tool_use") or result.get("addressed_to") or result.get("requests_to_prime")
    if not took_action:
        return None
    response = (result.get("response") or "").strip()
    if not response:
        return None
    return response[:_HISTORY_FALLBACK_CHARS] + ("..." if len(response) > _HISTORY_FALLBACK_CHARS else "")


def truncate_output(text: str, max_chars: int = 2500, head_chars: int = 1500) -> str:
    """Caps long tool output (e.g. a multi-thousand-line pytest traceback)
    before it hits a prompt/DB row/console dump. Keeps head + tail."""
    if not text or len(text) <= max_chars:
        return text or ""
    tail_chars = max_chars - head_chars
    omitted = len(text) - max_chars
    return (
        f"{text[:head_chars]}\n"
        f"... ({omitted} chars truncated — showing first failure + final summary) ...\n"
        f"{text[-tail_chars:]}"
    )


# This report only ever gets shown once (it lives in the vanishing EPHEMERAL
# tier -- see graph.py's last_tool_results_text), so a much bigger cap here
# costs one turn's worth of extra tokens, never a running total. That one-
# time spike is worth it: the old 2500-char head+tail cut was hiding the
# actual traceback for every failure except the first when several tests
# ERRORed at once, forcing several extra turns of guessing at the real cause.
_EPHEMERAL_MAX_CHARS = 20_000
_EPHEMERAL_HEAD_CHARS = 14_000


def _truncate_ephemeral(text: str) -> str:
    return truncate_output(text, max_chars=_EPHEMERAL_MAX_CHARS, head_chars=_EPHEMERAL_HEAD_CHARS)


def format_tool_results(executed: list[dict]) -> str:
    """Reports EVERY tool call's real outcome from this turn, not just
    run_shell/install_package -- a reflecting role that also called
    write_file/edit_file this turn must see whether that one actually
    succeeded too, or it has no way to know its own file write already
    landed and will defensively (and now, since write_file rejects an
    already-existing target, wastefully) reissue it."""
    lines = []
    for e in executed:
        kind = e.get("kind")
        if kind == "run_shell":
            status = "SUCCEEDED (exit 0)" if e["success"] else f"FAILED (exit {e.get('returncode', '?')})"
            lines.append(
                f"--- run_shell(\"{e['command']}\") — {status} ---\n"
                f"stdout: {_truncate_ephemeral(e.get('stdout')) or '(empty)'}\n"
                f"stderr: {_truncate_ephemeral(e.get('stderr') or e.get('error')) or '(empty)'}"
            )
        elif kind == "install_package":
            status = "SUCCEEDED" if e["success"] else "FAILED"
            detail = e.get("installed") if e["success"] else _truncate_ephemeral(e.get("error"))
            lines.append(f"--- install_package({e['packages']}) — {status} ---\n{detail}")
        elif kind in ("write_file", "edit_file"):
            status = "SUCCEEDED" if e["success"] else "FAILED"
            detail = f"wrote {e.get('bytes_written')} bytes" if e["success"] else _truncate_ephemeral(e.get("error"))
            lines.append(f"--- {kind}(path=\"{e.get('path')}\") — {status} ---\n{detail}")
        elif kind == "read_file":
            status = "SUCCEEDED" if e["success"] else "FAILED"
            detail = _truncate_ephemeral(e.get("content")) if e["success"] else e.get("error")
            lines.append(f"--- read_file(path=\"{e.get('path')}\") — {status} ---\n{detail}")
        elif kind == "list_dir":
            status = "SUCCEEDED" if e["success"] else "FAILED"
            detail = "\n".join(e.get("entries", [])) if e["success"] else e.get("error")
            lines.append(f"--- list_dir(path=\"{e.get('path')}\") — {status} ---\n{detail}")
    return "\n\n".join(lines) if lines else "(no tool results this turn)"


# Kinds worth showing the role its actual output for -- run_shell/
# install_package/read_file/list_dir always (the role has no other way to
# see them), write_file/edit_file only on failure (success is already
# visible via role_activity + the live sandbox file listing, no need to
# duplicate it in the vanishing tool-results tier).
def has_reportable_tool_results(executed: list[dict]) -> bool:
    return any(
        e.get("kind") in ("run_shell", "install_package", "read_file", "list_dir")
        for e in executed
    ) or any(
        e.get("kind") in ("write_file", "edit_file") and not e.get("success", True)
        for e in executed
    )


def _tool_error_key(e: dict) -> str | None:
    """Identifies *what* failed/succeeded so a later success on the same
    target can clear the matching open error -- not tied to which role or
    turn touched it."""
    kind = e.get("kind")
    if kind == "run_shell":
        return f"run_shell:{e.get('command')}"
    if kind == "install_package":
        return f"install_package:{e.get('packages')}"
    if kind in ("write_file", "edit_file", "read_file", "list_dir"):
        return f"{kind}:{e.get('path')}"
    return None


def _tool_error_text(e: dict) -> str:
    kind = e.get("kind")
    if kind == "run_shell":
        return (f"--- run_shell(\"{e.get('command')}\") still FAILING "
                f"(exit {e.get('returncode', '?')}) ---\n"
                f"stderr: {truncate_output(e.get('stderr') or e.get('error')) or '(empty)'}")
    if kind == "install_package":
        return (f"--- install_package({e.get('packages')}) still FAILING ---\n"
                f"{truncate_output(e.get('error'))}")
    if kind in ("write_file", "edit_file", "read_file", "list_dir"):
        return f"--- {kind}(path=\"{e.get('path')}\") still FAILING ---\n{truncate_output(e.get('error'))}"
    return ""


def update_open_tool_errors(open_errors: dict[str, str], executed: list[dict]) -> dict[str, str]:
    """Resolution-driven, not turn-count-driven: a failure is added under a
    key identifying its target, and removed the moment a later call against
    that same target succeeds -- regardless of how many turns that takes."""
    updated = dict(open_errors)
    for e in executed:
        key = _tool_error_key(e)
        if key is None:
            continue
        if e.get("success", True):
            updated.pop(key, None)
        else:
            updated[key] = _tool_error_text(e)
    return updated


def format_open_errors(open_errors: dict[str, str]) -> str:
    if not open_errors:
        return "(none currently open)"
    return "\n\n".join(open_errors.values())


def execute_tool_calls(task_spec_id: int, role_name: str, tool_use: list[dict],
                        failure_context: str, turn: int, full_roster: list[dict],
                        protected_paths: list[str]) -> list[dict]:
    executed = []
    for t in tool_use:
        tool = t["tool"]

        if tool == "read_file":
            rel_path = t["path"]
            allowed, reason = check_read_allowed(role_name, rel_path, full_roster)
            if not allowed:
                print(f"    [EXECUTOR] REJECTED read_file {rel_path}: {reason}")
                result = {"path": rel_path, "success": False, "error": reason, "kind": "read_file"}
                executed.append(result)
                continue

            print(f"    [EXECUTOR] reading {rel_path}")
            result = execute_read_file(task_spec_id, rel_path)
            result["kind"] = "read_file"
            executed.append(result)
            if not result["success"]:
                print(f"    [EXECUTOR] FAILED read_file {rel_path}: {result['error']}")
            continue

        if tool == "list_dir":
            rel_path = t.get("path") or "."
            print(f"    [EXECUTOR] listing {rel_path}")
            result = execute_list_dir(task_spec_id, rel_path)
            result["kind"] = "list_dir"
            executed.append(result)
            if not result["success"]:
                print(f"    [EXECUTOR] FAILED list_dir {rel_path}: {result['error']}")
            continue

        if tool == "write_file":
            rel_path = t["path"]
            allowed, reason = check_and_claim_ownership(task_spec_id, role_name, rel_path,
                                                          full_roster, protected_paths)
            if not allowed:
                print(f"    [EXECUTOR] REJECTED write_file {rel_path}: {reason}")
                result = {"path": rel_path, "success": False, "error": reason, "kind": "write_file"}
                executed.append(result)
                save_role_activity(task_spec_id, role_name, "write_file",
                                    f"REJECTED: {rel_path} (ownership: {reason})", turn=turn)
                continue

            print(f"    [EXECUTOR] generating {rel_path} via executor LLM ...")
            result = execute_write_file(task_spec_id, rel_path, t["why"], failure_context)
            result["kind"] = "write_file"
            executed.append(result)
            if result["success"]:
                print(f"    [EXECUTOR] wrote {result['resolved_path']} ({result['bytes_written']} bytes)")
                save_role_activity(task_spec_id, role_name, "write_file", f"wrote {rel_path}", turn=turn)
            else:
                print(f"    [EXECUTOR] FAILED write_file {rel_path}: {result['error']}")
                save_role_activity(task_spec_id, role_name, "write_file", f"FAILED: {rel_path}", turn=turn)
            continue

        if tool == "edit_file":
            edit_path = t["path"]
            allowed, reason = check_and_claim_ownership(task_spec_id, role_name, edit_path,
                                                          full_roster, protected_paths)
            if not allowed:
                print(f"    [EXECUTOR] REJECTED edit_file {edit_path}: {reason}")
                result = {"path": edit_path, "success": False, "error": reason, "kind": "edit_file"}
                executed.append(result)
                save_role_activity(task_spec_id, role_name, "edit_file",
                                    f"REJECTED: {edit_path} (ownership: {reason})", turn=turn)
                continue

            print(f"    [EXECUTOR] patching {edit_path} via executor LLM ...")
            result = execute_edit_file(task_spec_id, edit_path, t["why"], failure_context)
            result["kind"] = "edit_file"
            executed.append(result)
            if result["success"]:
                fallback_note = " (fell back to full rewrite)" if result.get("fallback_to_write_file") else ""
                print(f"    [EXECUTOR] patched {result['resolved_path']} "
                      f"({result['bytes_written']} bytes){fallback_note}")
                save_role_activity(task_spec_id, role_name, "edit_file",
                                    f"edited {edit_path}{fallback_note}", turn=turn)
            else:
                print(f"    [EXECUTOR] FAILED edit_file {edit_path}: {result['error']}")
                save_role_activity(task_spec_id, role_name, "edit_file", f"FAILED: {edit_path}", turn=turn)
            continue

        if tool == "run_shell":
            command = t["command"]
            print(f"    [EXECUTOR] running shell: {command}")
            result = execute_run_shell(task_spec_id, command)
            result["kind"] = "run_shell"
            executed.append(result)
            if result["success"]:
                print("    [EXECUTOR] shell ok (exit 0)")
                save_role_activity(task_spec_id, role_name, "run_shell", f"ran: {command}", turn=turn)
            else:
                error = truncate_output(result.get("error") or result.get("stderr")) or "(empty stderr)"
                returncode = result.get("returncode", "?")
                stdout = truncate_output(result.get("stdout")) or "(empty stdout)"
                print(f"    [EXECUTOR] FAILED run_shell (exit {returncode}): {error}")
                print(f"    [EXECUTOR]   stdout: {stdout}")
                save_role_activity(task_spec_id, role_name, "run_shell",
                                    f"FAILED (exit {returncode}): {command}"[:200], turn=turn)
            continue

        if tool == "install_package":
            packages = t["packages"]
            print(f"    [EXECUTOR] installing packages: {packages}")
            result = execute_install_package(packages)
            result["kind"] = "install_package"
            executed.append(result)
            if result["success"]:
                print(f"    [EXECUTOR] installed {result['installed']}")
                for pkg, version in result["installed"].items():
                    save_role_activity(task_spec_id, role_name, "install_package",
                                        f"installed {pkg}=={version}", turn=turn)
            else:
                print(f"    [EXECUTOR] FAILED install_package: {result['error']}")
                save_role_activity(task_spec_id, role_name, "install_package",
                                    f"FAILED: {packages}", turn=turn)
            continue

    return executed
