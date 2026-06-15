---
name: build-step
description: >
  Implements one numbered build step end to end using multiple agents automatically.
  Use when the user says "start step N", "build step N", or "implement step N".
---

## When This Skill Runs

Triggered by: "start step [N]", "build step [N]", "implement [step name]", "do step [N]"

## What Happens (Multi-Agent Pipeline)

The skill runs agents automatically in this order:

### Phase A — Read the Step (plan-reader agent)
Run the `plan-reader` agent to extract:
- Exact requirements for the step
- Files to create/modify
- Demo criteria
- Whether security audit is needed

### Phase B — Implement
Implement the step based on plan-reader's output:
1. Create/modify all files listed
2. Follow `.claude/rules/backend.md` and `.claude/rules/frontend.md`
3. Write tests as specified
4. Do not implement anything beyond the step's scope

### Phase C — Test (test-runner agent)
Run the `test-runner` agent:
- If STATUS: PASS → continue
- If STATUS: FAIL → fix the failing tests, then re-run test-runner
- If STATUS: BLOCKED → report to the user; do not continue

### Phase D — Review (code-reviewer agent)
Run the `code-reviewer` agent on the diff:
- If STATUS: PASS → continue
- If STATUS: FAIL → fix CRITICAL issues, re-run reviewer
- WARN issues: fix if easy; note them in dev-log if deferred

### Phase E — Security Audit (security-auditor agent, conditional)
Run only if plan-reader flagged "Security audit needed: yes".
- If STATUS: PASS → continue
- If STATUS: FAIL → fix all CRITICAL security issues before proceeding

### Phase F — Validate (build-validator agent)
Run the `build-validator` agent:
- If STATUS: PASS → proceed to Phase G
- If STATUS: FAIL → fix missing items, re-run validator

### Phase G — Update Docs
1. Update `docs/current-state.md`: add what was built in this step
2. Append a dated entry to `docs/dev-log.md`
3. Update `plan/BUILD-TRACKER.md`: mark the step `[x]`
4. Commit: `git commit -m "feat: [step description]"`

## Output to User

After all phases complete, report:
- What was built (files created/modified)
- Test results (N passed)
- Any deferred WARN issues
- The commit hash
- What the next step is (from BUILD-TRACKER.md)

## Constraints

- Never skip Phase C (tests) or Phase D (review).
- Never mark a step `[x]` if tests are failing.
- Never implement beyond the current step's scope. If you see something that could
  be improved outside the step, note it in dev-log and move on.
- If any agent returns BLOCKED, stop and report to the user. Do not guess.
