# Recruiting Offer Negotiation — Private-Information Multi-Agent Task

## Title
Recruiting Offer Negotiation — Private-Information Multi-Agent Task

## Objective
Negotiate a final compensation package for a specific software engineering
role between a **Hiring Manager** and a **Candidate Representative** (the
role that directly represents the candidate's own interest in this
negotiation), inside one isolated sandbox project folder, ending in either
a signed offer or a documented no-deal. This is the recognizable
"AI-assisted recruiting negotiation" pattern. The two parties do not share
the same information: the Candidate privately knows their own true
minimum; the Hiring Manager privately knows the team's true limits — and
in this version of the task, **base salary alone does NOT have a workable
overlap** between the two private positions. A deal, if one is reached, is
only reachable by negotiating across more than one dimension (base salary,
signing bonus, equity) — this specifically tests whether the negotiation
can discover and use levers beyond the single number both sides start by
anchoring on, and whether a genuine no-deal is correctly recorded when it's
the honest outcome, rather than the roles forcing an agreement that
violates one side's real limit just to produce a tidy result.

## How the negotiation actually works (read this before assigning roles)
- `recruiting/role_package_template.md` already exists in the sandbox
  (pre-seeded, protected, readable by both roles) — it defines the posted
  base salary range and the outer limits of the two additional levers
  (signing bonus, equity). Read it before making any offer; do not invent
  different limits.
- Each party has its own private true position (see Baseline Parameters) —
  neither party's prompt contains the other's private figures, and neither
  may state its own private figures verbatim to the other (Constraint 3).
- Negotiate in real rounds: one party states an opening package (base +
  signing bonus + equity, using $0/0% for any lever not offered), the
  other responds with either an acceptance, a counter-package, or a
  specific objection naming which part of the package doesn't work for
  them — not a vague "that doesn't work," but "the base is below what I
  can accept" or similar, since the other side can only usefully adjust a
  lever it knows is the actual problem.
- If, after real back-and-forth exploring more than one lever, no package
  exists that both sides can genuinely accept under their own private
  limits, record an explicit no-deal — this is a legitimate, correct
  outcome for this task, not a failure to fix by inventing a private limit
  isn't real.

## Location
This is a virtual, sandboxed task with no physical site.
- City: N/A (sandboxed)
- Region: N/A (sandboxed)
- Area description: Isolated local project folder created for this task
  only. No physical location is involved; all work happens inside the
  sandbox root and must never touch the AGNIES project's own environment or
  files outside the sandbox boundary. This task produces negotiation
  records and a final agreement document, not code.

## Budget
Budget for this task is measured in LLM calls, not currency. Assume a
working budget of 40 LLM calls total across both roles for this run
(ASSUMED — a benchmark limit set for this test run; slightly higher than
the original version since a genuinely tight, multi-dimensional
negotiation takes more real back-and-forth than a comfortable single-number
overlap would).

## Duration
Target wall-clock duration for this task is 30 minutes (ASSUMED — a
benchmark limit set for this test run, not a stated fact).

## Constraints
These are hard rules the running agents must not violate:

1. **Sandbox boundary.** Every file and shell tool call must resolve its
   target path and reject anything that would escape the sandbox root.
2. **File ownership.** Each role may freely read any file it is permitted
   to in the sandbox, but may only write files inside the path(s) it is
   assigned to own.
3. **No direct disclosure of private figures.** Neither role may state its
   own private true limit (on any lever) verbatim to the other party, in
   `response` or `addressed_to` text — negotiate through packages,
   counter-packages, and stated objections instead. Stating a firm number
   as part of an actual offer/counter-offer is expected and required;
   stating "my true minimum/maximum is exactly $X" is not.
4. **Stay within the shared framework's limits.** Neither party may offer
   or request a signing bonus or equity grant outside the bounds stated in
   `recruiting/role_package_template.md`.
5. **No fabricated facts or results.** Neither role may claim the other
   party agreed to something it did not actually state in the negotiation
   record. A final agreement must reflect terms both sides actually
   confirmed.
6. **A genuine no-deal is an acceptable outcome.** Do not force an
   agreement that would require either side to accept a package outside
   its own real private limits, and do not silently drop the negotiation
   without a documented outcome either way.
7. **Verified success only.** The task is only complete once its automated
   verification step passes; narrating that "we're close to a deal" does
   not count as done — there must be a real recorded final outcome.

## Baseline Parameters
- `candidate_true_minimum_base_usd`: 115000, unit: USD/year, source:
  ASSUMED (known ONLY to the Candidate Representative — the lowest base
  salary they would accept with no other lever offered).
- `candidate_bonus_flex_note`: "Would accept a base as low as
  $108,000 if paired with a signing bonus of at least $12,000, since that
  offsets the first-year gap; would not go below $108,000 base under any
  package.", source: ASSUMED (known ONLY to the Candidate Representative —
  private guidance on how they personally value trading base for other
  levers; not itself a number to be recomputed or overridden).
- `hiring_true_base_ceiling_usd`: 108000, unit: USD/year, source: ASSUMED
  (known ONLY to the Hiring Manager — the team's real maximum base salary
  for this role; note this is BELOW the Candidate's stated
  `candidate_true_minimum_base_usd` on base salary alone).
- `hiring_lever_preference_note`: "Would strongly prefer to offer a
  signing bonus or equity over exceeding the base salary ceiling, for
  internal pay-equity reasons; authorized to offer up to the full signing
  bonus and equity limits in the shared framework if it avoids raising
  base salary.", source: ASSUMED (known ONLY to the Hiring Manager).
- `role_title_for_market_search`: "Backend Software Engineer, mid-level,
  Bangalore", unit: n/a, source: ASSUMED (the exact role/location the
  Hiring Manager must ground a real current market search against).

## Interventions
The components needed to satisfy the objective:

- category: negotiation, name: A real, multi-round exchange of packages
  (base + signing bonus + equity) between the Hiring Manager and the
  Candidate Representative, each grounded in the shared framework's limits
  and each side's own private position, exploring more than base salary
  alone once a bare base-salary anchor proves insufficient.
- category: market_grounding, name: A real grounded-search resolution of
  the current market salary range for `role_title_for_market_search`,
  performed once and referenced by the Hiring Manager during negotiation
  (via the existing fact-resolution mechanism — never guessed).
- category: agreement, name: A final written agreement document recording
  either the fully agreed package (base + signing bonus + equity) and any
  other agreed terms, or an explicit documented no-deal outcome with the
  specific reason negotiations did not converge.

## Metrics
- name: deal_reached, objective: increase
- name: private_information_leaked, objective: stay_within
- name: unresolved_search_needed_requests, objective: reduce

## Success Criteria
- `recruiting/negotiation_log.md` exists and records the real sequence of
  packages/counter-packages exchanged between both roles, including the
  Hiring Manager's referenced real market-data finding.
- `recruiting/final_agreement.md` exists and states either a specific
  agreed package (base salary, signing bonus, equity) with any other
  agreed terms, or an explicit no-deal outcome with a stated reason — not
  a vague "still discussing" state.
- If a deal was reached, the agreed package is actually acceptable under
  BOTH private positions as stated in Baseline Parameters (e.g. a
  $108,000 base with at least a $12,000 signing bonus satisfies the
  Candidate's stated flex note; a $115,000 flat base with no other lever
  does not, since it exceeds the Hiring Manager's true ceiling) — verified
  by an independent reviewer checking the final package against both
  private figures/notes, which the reviewer (unlike either role during the
  negotiation) is allowed to see.
- If no deal was reached, the negotiation log shows that more than one
  lever (not just base salary) was genuinely explored before concluding
  no-deal — a no-deal reached without ever discussing signing bonus or
  equity is not a properly tested outcome for this task.
- Neither role's `response`/`addressed_to` text anywhere in the negotiation
  record states the other party's or its own private figure verbatim —
  verified by an independent reviewer reading the real negotiation log
  against both private figures.
- The Hiring Manager's real-market-data claim is grounded in an actual
  resolved fact (via the existing grounded-search mechanism), not asserted
  from unverified memory.
- No tool call during the task escaped the sandbox root or touched the
  AGNIES project's own environment.

## Provenance
Internal test task authored for the AGNIES project to exercise genuine
per-role information isolation (`private_context`, never shared across
roles) under a recognizable real-world negotiation pattern. Revised from an
earlier version after review found the original base-salary overlap
($105k-$115k) was comfortable enough that a deal was reachable without any
real negotiation skill — this version removes the base-salary overlap
entirely and requires discovering value across signing bonus/equity
instead, so reaching (or correctly failing to reach) a deal actually
depends on the negotiation working, not on generous starting numbers.
`ROLE_CATALOG` was also missing matching archetypes for either role in the
original version; "Hiring Manager" and "Candidate Representative" have
been added. This is the one task in this batch specifically designed to
prove something a single self-negotiating agent cannot authentically
demonstrate: a real information boundary between two parties, provable by
inspecting what each role's own prompt did and did not contain. Not derived
from an external document; the task itself, its constraints, and its
success criteria are stated directly above and are REAL by definition of
being the authoritative source for this run. (REAL)
