import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from .agent_shell import extract_usage
from .config import FILE_EDIT_INSTRUCTIONS, FILE_GENERATION_INSTRUCTIONS
from .llm_factory import build_chat_model
from .retry import call_with_retry

load_dotenv()

SANDBOX_ROOT = Path(
    os.environ.get("SANDBOX_ROOT", r"C:\Users\souls\Desktop\Manoj\Sandbox")
)
VENV_DIR = SANDBOX_ROOT / ".venv"
VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
REQUIREMENTS_PATH = SANDBOX_ROOT / "requirements.txt"

# Best-effort run_shell escape patterns — cwd is already pinned to the task
# folder, so a legitimate command never needs any of these.
_SHELL_FORBIDDEN_PATTERNS = [
    re.compile(r'\.\.'),                 # parent-directory traversal
    re.compile(r'[A-Za-z]:[\\/]'),       # absolute drive-letter path
    re.compile(r'\bcd\b'),               # directory changes (cwd already pinned)
]

_PYTHON3_INVOCATION_RE = re.compile(r'\bpython3\b(?!\.\d)')


def _normalize_python_invocation(command: str) -> str:
    return _PYTHON3_INVOCATION_RE.sub("python", command)


def _venv_shell_env(cwd: Path) -> dict:
    """Same environment shape as ownership.check_verification's shell_command
    step -- every run_shell call must see the sandbox's own activated .venv
    (installed packages, its own python.exe), not whatever's on the worker
    process's inherited PATH."""
    env = os.environ.copy()
    env["PATH"] = str(VENV_DIR / "Scripts") + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(VENV_DIR)
    env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")
    return env


class SandboxViolation(Exception):
    pass


def task_sandbox_dir(task_spec_id: int) -> Path:
    return SANDBOX_ROOT / f"task_{task_spec_id}"

_SANDBOX_LISTING_EXCLUDED_DIRS = {
    # Python virtualenvs and caches
    ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".eggs", ".ipynb_checkpoints",
    # Node/JS dependency and build output
    "node_modules", ".next", ".nuxt", ".parcel-cache",
    # Generic build/dist output (any ecosystem)
    "build", "dist", "target", "bin", "obj",
    # Version control
    ".git", ".svn", ".hg",
    # Editor/IDE metadata
    ".idea", ".vscode", ".vs",
    # Coverage/test-artifact output
    ".coverage", "htmlcov", ".nyc_output",
    # OS junk files
    ".DS_Store", "Thumbs.db", "desktop.ini",
    # Misc caches
    ".cache",
}

def snapshot_existing_files(task_spec_id: int) -> list[str]:
    base = task_sandbox_dir(task_spec_id)
    base.mkdir(parents=True, exist_ok=True)
    return sorted(
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file()
        and not _SANDBOX_LISTING_EXCLUDED_DIRS.intersection(path.relative_to(base).parts)
    )

PRIVATE_SEED_ROOT = Path(r"C:\Users\souls\Desktop\Manoj\AGNEIS\planning\private_md")

def seed_private_files(task_spec_id: int, source_filename: str) -> list[str]:

    seed_dir = PRIVATE_SEED_ROOT / Path(source_filename).stem
    if not seed_dir.is_dir():
        return []

    sandbox_dir = task_sandbox_dir(task_spec_id)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    seeded = []
    for src in sorted(p for p in seed_dir.rglob("*") if p.is_file()):
        rel = src.relative_to(seed_dir).as_posix()
        dst = sandbox_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        seeded.append(rel)
    return seeded


def clear_sandbox_dir(task_spec_id: int) -> None:
    sandbox_dir = task_sandbox_dir(task_spec_id)
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

def resolve_sandbox_path(task_spec_id: int, relative_path: str) -> Path:

    base = task_sandbox_dir(task_spec_id).resolve()
    candidate = (base / relative_path).resolve()
    if candidate != base and base not in candidate.parents:
        raise SandboxViolation(
            f"Path {relative_path!r} resolves to {candidate}, which escapes "
            f"the task sandbox {base}"
        )
    return candidate


def _excluded_path_reason(task_spec_id: int, target: Path) -> str | None:
    """Same exclusion list as the automatic listings (snapshot_existing_files,
    gather_sibling_files_context) -- a role's own explicit read_file/list_dir
    call had no equivalent guard, so it could still deliberately (or by
    confused imitation of a path it saw truncated elsewhere) target .venv/
    dist/node_modules/etc. and get served real content from it. Returns a
    rejection reason, or None if the path is fine."""
    base = task_sandbox_dir(task_spec_id).resolve()
    try:
        rel_parts = target.relative_to(base).parts
    except ValueError:
        return None
    hit = _SANDBOX_LISTING_EXCLUDED_DIRS.intersection(rel_parts)
    if hit:
        return (f"{'/'.join(rel_parts)!r} is inside/matches an excluded dependency/build/VCS "
                f"artifact ({sorted(hit)[0]!r}) -- not something you own or need to read/list.")
    return None


_MAX_READ_FILE_CHARS = 20_000

def execute_read_file(task_spec_id: int, relative_path: str) -> dict:
    try:
        target = resolve_sandbox_path(task_spec_id, relative_path)
    except SandboxViolation as e:
        return {"path": relative_path, "success": False, "error": str(e)}
    excluded_reason = _excluded_path_reason(task_spec_id, target)
    if excluded_reason:
        return {"path": relative_path, "success": False, "error": excluded_reason}
    if not target.is_file():
        return {"path": relative_path, "success": False, "error": f"no such file: {relative_path!r}"}
    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > _MAX_READ_FILE_CHARS
    if truncated:
        content = content[:_MAX_READ_FILE_CHARS] + "\n... (truncated)"
    return {"path": relative_path, "success": True, "content": content, "truncated": truncated}

def execute_list_dir(task_spec_id: int, relative_path: str | None) -> dict:

    rel = relative_path or "."
    try:
        target = resolve_sandbox_path(task_spec_id, rel)
    except SandboxViolation as e:
        return {"path": rel, "success": False, "error": str(e)}
    excluded_reason = _excluded_path_reason(task_spec_id, target)
    if excluded_reason:
        return {"path": rel, "success": False, "error": excluded_reason}
    target.mkdir(parents=True, exist_ok=True) if rel == "." else None
    if not target.is_dir():
        return {"path": rel, "success": False, "error": f"no such directory: {rel!r}"}
    entries = sorted(p.name + "/" if p.is_dir() else p.name for p in target.iterdir())
    return {"path": rel, "success": True, "entries": entries}


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text

EXECUTOR_MODEL = os.environ["ROLE_MODEL"]
_executor_llm = build_chat_model(EXECUTOR_MODEL)

def _format_failure_context(failure_context: str) -> str:
    if not failure_context:
        return ""
    return (
        "\n--- MOST RECENT run_shell/install_package FAILURE (REAL, VERBATIM "
        "output -- if the spec above contradicts this, trust THIS, not the spec) ---\n"
        f"{failure_context}\n--- END MOST RECENT FAILURE ---\n"
    )

def _invoke_executor(instructions: str, label: str) -> tuple[str, dict]:
    """Returns (content, usage) -- this LLM call was previously untracked:
    it returned only the generated text, so every write_file/edit_file's
    real token cost never reached the run's totals (graph.py's
    _accumulate_tokens never saw it). usage flows back through
    generate_file_content/generate_edit_patch -> execute_write_file/
    execute_edit_file -> execute_tool_calls -> execute_tools_node from here.

    Deliberately stateless and spec-only: the executor never sees the task
    spec, verification, or any other project context -- only the role's own
    `spec` text (plus sibling-file/failure context), the same instruction a
    human executing that spec would get. Any literal/exact-format text a
    role must reproduce belongs in the role's spec itself (the role has
    NORMATIVE SPEC in its own prompt for exactly this), not smuggled in here."""
    prompt = instructions

    def _call() -> tuple[str, dict]:
        response = _executor_llm.invoke(prompt)
        content = _extract_text(response)
        if not content.strip():
            raise RuntimeError("executor LLM call returned empty content")
        return content, extract_usage(response)

    return call_with_retry(_call, label=label)


def _extract_text(response) -> str:

    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)

_MAX_SIBLING_FILE_CHARS = 4000

def gather_sibling_files_context(task_spec_id: int, exclude_path: str) -> str:

    base = task_sandbox_dir(task_spec_id)
    if not base.exists():
        return "(no files written yet)"

    exclude_resolved = (base / exclude_path).resolve()
    sections = []
    for path in sorted(base.rglob("*")):
        if path.is_dir() or path.resolve() == exclude_resolved:
            continue
        rel = path.relative_to(base).as_posix()
        if _SANDBOX_LISTING_EXCLUDED_DIRS.intersection(path.relative_to(base).parts):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > _MAX_SIBLING_FILE_CHARS:
            content = content[:_MAX_SIBLING_FILE_CHARS] + "\n... (truncated)"
        sections.append(f"--- {rel} ---\n{content}")

    return "\n\n".join(sections) if sections else "(no files written yet)"


def generate_file_content(relative_path: str, spec: str,
                           failure_context: str, sibling_files_context: str) -> tuple[str, dict]:
    instructions = FILE_GENERATION_INSTRUCTIONS.format(
        relative_path=relative_path,
        failure_context=_format_failure_context(failure_context),
        sibling_files_context=sibling_files_context,
        spec=spec,
    )
    stdout, usage = _invoke_executor(instructions,
                                      label=f"generate_file_content({relative_path}) executor LLM call")
    return _strip_code_fence(stdout), usage


def execute_write_file(task_spec_id: int, relative_path: str, spec: str,
                        failure_context: str = "") -> dict:

    try:
        target = resolve_sandbox_path(task_spec_id, relative_path)
    except SandboxViolation as e:
        return {"path": relative_path, "success": False, "error": str(e)}

    if target.exists():
        return {
            "path": relative_path, "success": False,
            "error": f"{relative_path!r} already exists — use edit_file to change it, "
                     f"not write_file (write_file only creates a NEW file).",
        }

    try:
        sibling_context = gather_sibling_files_context(task_spec_id, relative_path)
        content, usage = generate_file_content(relative_path, spec, failure_context, sibling_context)
    except Exception as e:
        return {"path": relative_path, "success": False, "error": str(e)}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return {
        "path": relative_path,
        "resolved_path": str(target),
        "success": True,
        "bytes_written": len(content),
        "usage": usage,
    }


def generate_edit_patch(relative_path: str, current_content: str, spec: str,
                         failure_context: str, sibling_files_context: str) -> tuple[dict, dict]:

    instructions = FILE_EDIT_INSTRUCTIONS.format(
        relative_path=relative_path,
        current_content=current_content,
        failure_context=_format_failure_context(failure_context),
        sibling_files_context=sibling_files_context,
        spec=spec,
    )
    stdout, usage = _invoke_executor(instructions,
                                      label=f"generate_edit_patch({relative_path}) executor LLM call")
    raw = _strip_code_fence(stdout)
    try:
        patch = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"edit_file patch was not valid JSON ({e}): {raw[:500]!r}")
    if not isinstance(patch, dict) or "old_string" not in patch or "new_string" not in patch:
        raise RuntimeError(f"edit_file patch missing old_string/new_string: {raw[:500]!r}")
    return patch, usage


def execute_edit_file(task_spec_id: int, relative_path: str, spec: str,
                       failure_context: str = "") -> dict:

    try:
        target = resolve_sandbox_path(task_spec_id, relative_path)
    except SandboxViolation as e:
        return {"path": relative_path, "success": False, "error": str(e)}

    if not target.exists():
        result = execute_write_file(task_spec_id, relative_path, spec, failure_context)
        result["fallback_to_write_file"] = True
        return result

    try:
        current_content = target.read_text(encoding="utf-8", errors="replace")
        sibling_context = gather_sibling_files_context(task_spec_id, relative_path)
        patch, usage = generate_edit_patch(relative_path, current_content, spec,
                                            failure_context, sibling_context)
    except Exception as e:
        return {"path": relative_path, "success": False, "error": str(e)}

    old_string, new_string = patch["old_string"], patch["new_string"]
    occurrences = current_content.count(old_string)
    if occurrences == 0:
        return {
            "path": relative_path, "success": False,
            "error": "edit_file patch's old_string was not found verbatim in the current file contents",
            "usage": usage,
        }
    if occurrences > 1:
        return {
            "path": relative_path, "success": False,
            "error": f"edit_file patch's old_string is ambiguous ({occurrences} matches) — "
                     f"needs more surrounding context to be unique",
            "usage": usage,
        }

    new_content = current_content.replace(old_string, new_string, 1)
    target.write_text(new_content, encoding="utf-8")

    return {
        "path": relative_path,
        "resolved_path": str(target),
        "success": True,
        "bytes_written": len(new_content),
        "usage": usage,
    }


def execute_run_shell(task_spec_id: int, command: str) -> dict:

    for pattern in _SHELL_FORBIDDEN_PATTERNS:
        if pattern.search(command):
            return {
                "command": command,
                "success": False,
                "error": f"Command rejected — matched forbidden pattern {pattern.pattern!r}",
            }

    cwd = task_sandbox_dir(task_spec_id)
    cwd.mkdir(parents=True, exist_ok=True)
    command = _normalize_python_invocation(command)

    result = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        env=_venv_shell_env(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return {
        "command": command,
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def _get_installed_version(package: str) -> str | None:
    result = subprocess.run(
        [str(VENV_PIP), "show", package],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Version:"):
            return line.split(":", 1)[1].strip()
    return None


def _update_requirements_txt(installed: dict[str, str]) -> None:

    existing: dict[str, str] = {}
    if REQUIREMENTS_PATH.exists():
        for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or "==" not in line:
                continue
            name, version = line.split("==", 1)
            existing[name.strip().lower()] = version.strip()

    for package, version in installed.items():
        if version is not None:
            existing[package.lower()] = version

    lines = [f"{name}=={version}" for name, version in sorted(existing.items())]
    REQUIREMENTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute_install_package(packages: list[str]) -> dict:

    if not VENV_PIP.exists():
        return {
            "packages": packages,
            "success": False,
            "error": f"venv pip not found at {VENV_PIP} — sandbox .venv missing or malformed",
        }

    result = subprocess.run(
        [str(VENV_PIP), "install", *packages],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if result.returncode != 0:
        return {
            "packages": packages,
            "success": False,
            "error": result.stderr,
        }

    installed = {pkg: _get_installed_version(pkg) for pkg in packages}
    _update_requirements_txt(installed)

    return {
        "packages": packages,
        "success": True,
        "installed": installed,
        "requirements_path": str(REQUIREMENTS_PATH),
    }
