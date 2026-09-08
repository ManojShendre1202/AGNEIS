import os

from dotenv import load_dotenv

from backend.agnies.schemas import TaskSpec
from backend.core.services.resource_pool_service import ResourcePoolService
from backend.core.services.roster_entry_service import RosterEntryService
from backend.core.services.task_spec_service import TaskSpecService

from ..negotiation.agent_shell import invoke_structured
from ..negotiation.llm_factory import cached_system_block, supports_prompt_caching

SOURCE_TEXT_BLOCK = """\
--- BEGIN SOURCE TEXT ---
{source_text}
--- END SOURCE TEXT ---
"""
EXTRACTION_INSTRUCTIONS = """\
Extract a structured task specification from the raw project brief given \
above. Only extract values stated or directly derivable from the text —
never invent. Tag each numeric/factual value's `source`: REAL (stated as
fact), DERIVED (calculated from real info in the text), ASSUMED (the text
itself labels it a benchmark/assumption, not a measured fact); never
GENERATED (that tag is only for values a later simulation creates, not
extraction). `constraints` must cover every "must not be violated" rule;
`dynamic_events` every named event (e.g. "Event A", "Event B", ...); empty
if the text names none — never invent one out of ordinary lifecycle steps
that aren't presented as a distinct named event.

If the text has a "Baseline Parameters" section (or any section stating
facts/figures known privately to only one party — a role's true minimum,
ceiling, ASSUMED preference, flex note, etc.), this TaskSpec has no
dedicated field for it, so it must NOT be left to survive only as a
fragment inside some other field (e.g. one illustrative example buried in a
success criterion written for a reviewer). Emit ONE separate Constraint per
private fact, kind="hard", name naming the role and the fact (e.g.
"candidate_true_minimum_base"), description = that fact's FULL value and
wording copied verbatim, plus which role alone may know it and that it must
never be disclosed to any other role. Every private fact from that section
must get its own constraint this way — none may be dropped, truncated, or
represented only via a downstream example meant for someone else's use
(like a reviewer who is allowed to see both sides).

`verification`: one VerificationStep per concrete, automatable pass/fail
check stated in the text, using the most specific `kind`:
- "shell_command": `command` + `expected_exit_code` (default 0). Proves the
  process didn't crash — never that its output was correct. Must be
  runnable exactly as given from the sandbox root — never assume a
  nested/renamed working directory (e.g. no `cd <dir> &&` prefix) unless
  the text itself names that directory. The sandbox is Windows, commands run
  in cmd.exe, NOT a POSIX shell — never emit a Unix-only command (grep,
  find with POSIX flags like -newer/-type, ls, cat, history, etc.) or a
  Unix flag on a Windows-native command; if you need to check a file's
  content matches something, prefer `file_matches` over a `grep`
  shell_command, since it doesn't depend on the shell at all.
- "file_exists": `path`. Proves the file is there — never that its content
  is right.
- "file_matches": `path` + `pattern` (regex derived from what the text
  requires the file to contain). `path` must be a FILE, never a directory.
- "llm_review": whenever the check is about CORRECTNESS OF CONTENT, not
  process survival (e.g. "produces correct output", "matches the spec",
  "is a genuine fact, not fabricated"). `criterion` = the requirement,
  quoted close to the source wording. `review_targets` = the exact
  sandbox-relative file path(s) and/or "shell_command:<command>" entries a
  reviewer must read as real evidence — any shell_command entry here is
  bound by the same Windows cmd.exe rule above, never a Unix-only command.

If the text requires both a command/file check AND correct output, emit
BOTH steps — a shell_command/file_exists/file_matches result never
substitutes for an llm_review of correctness. Check the entire text,
especially any "Success Criteria"/"Verification"/"Definition of Done"
section — these usually list several separate checks, not one. Before
finishing, check every bullet in that section against your list: one you
can't turn into a mechanical check still gets its own llm_review step —
never fold it into another step's criterion field, and never drop it
because a related mechanical check exists nearby. Only emit a step for
checks stated as automatable; return an empty list if the text describes
none.

`normative_spec_sections`: only sections defining an EXACT format/syntax/
contract work built for this task must conform to precisely (a grammar, an
API schema, a file format, a wire protocol, a config format, a fixed CLI
flag set) — anywhere a single wrong token/keyword/field name would make
the result incorrect, not just differently styled. Copy each such
section's `content` VERBATIM, character-for-character — do NOT paraphrase,
summarize, or "clean up", even if it looks verbose; a summary silently
loses the exact tokens that make it a contract. Most tasks have none —
return an empty list rather than inventing a section out of prose that
only describes intent (e.g. "the API should be RESTful") without literal
syntax.
"""


def _invoke_extraction(schema: type, instructions: str, source_text: str, label: str):
    model_spec = os.environ["PRIME_MODEL"]
    source_block = SOURCE_TEXT_BLOCK.format(source_text=source_text)

    if supports_prompt_caching(model_spec):
        messages = [
            {"role": "system", "content": [cached_system_block(source_block)]},
            {"role": "user", "content": instructions},
        ]
        return invoke_structured(model_spec, schema, messages, label=label)
    return invoke_structured(model_spec, schema, source_block + instructions, label=label)


def extract(source_text: str) -> TaskSpec:
    load_dotenv()

    extracted, usage = _invoke_extraction(
        TaskSpec, EXTRACTION_INSTRUCTIONS, source_text,
        label="extract_task_spec TaskSpec LLM call",
    )
    print(f"    [TOKENS] extract TaskSpec: input={usage['input_tokens']} output={usage['output_tokens']} "
          f"total={usage['total_tokens']}")
    print(f"    verification: {len(extracted.verification)} step(s); "
          f"normative_spec_sections: {len(extracted.normative_spec_sections)} section(s).")

    return extracted


def run_extract(task_spec_id: int) -> dict:
    task_spec_row = TaskSpecService.get(task_spec_id)
    extracted = extract(task_spec_row.raw_text)
    extracted_json = extracted.model_dump(mode="json")
    TaskSpecService.update_extracted(task_spec_id, extracted_json)
    RosterEntryService.delete_for_task(task_spec_id)
    ResourcePoolService.delete_for_task(task_spec_id)
    return {"extracted_json": extracted_json}
