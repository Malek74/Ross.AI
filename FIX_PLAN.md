# Ross.AI — Critical Fix Plan (pre-demo)

**Author:** review pass, 2026-07-18
**Audience:** implementer (Opus) working in a worktree, opening a draft PR.
**Scope:** Fix the *critical, safe, high-impact* bugs only. Bigger design changes are listed at the bottom as **Out of scope — needs steer**; do not attempt them without sign-off.

All line references below were verified against the current tree. Two claims from the original verbal review were **wrong** and are corrected here:

1. `.env` does **not** set `anthropic/claude-sonnet-4-5`. It sets `LLM_MODEL=qwen/qwen3.5-flash-02-23` (a Qwen *flash* model). The code default (`src/llm_client.py:41`) is `google/gemini-2.5-flash-lite`, but `.env` overrides it. So the running model is neither Sonnet nor flash-lite — it is Qwen flash. Still weak/inconsistent for long tool-use loops.
2. Nothing remaps the tool-output keys before the HTTP response. `src/agents/base_agent.py:142-145` attaches `tools.revisions` / `tools.drafts` to the result verbatim, so the field-name mismatches below reach the browser unrepaired.

---

## P0-A — Draft clauses render blank ("gibberish")

**Root cause:** backend/frontend field-name mismatch.

- Backend stores each draft as `{topic, clause_text, article_ref, rationale}` — `src/agents/tools.py:187-197`.
- Frontend `DraftClause` type expects `text` — `web/src/api/types.ts:21-25`.
- Frontend reads `clause.text` in two places — `web/src/components/ArtifactPanel.tsx:474` (print/export HTML) and `:492` (React `DraftReport`).
- `clause_text !== text` ⇒ body renders as `undefined`, and the RTL check `drafts.some(d => /[؀-ۿ]/.test(d.text))` (`ArtifactPanel.tsx:486`) always sees `undefined` ⇒ Arabic drafts wrongly render LTR.

**Fix — pick ONE side. Recommended: fix the frontend (keeps `topic` available for future use, one file, no API contract churn).**

Option A (frontend, recommended):
- `web/src/api/types.ts` — change `DraftClause` to:
  ```ts
  export interface DraftClause {
    topic?: string;
    clause_text: string;
    article_ref: string;
    rationale: string;
  }
  ```
- `web/src/components/ArtifactPanel.tsx:474` — `${esc(clause.text)}` → `${esc(clause.clause_text)}`
- `web/src/components/ArtifactPanel.tsx:486` — `d.text` → `d.clause_text`
- `web/src/components/ArtifactPanel.tsx:492` — `{clause.text}` → `{clause.clause_text}`

Option B (backend, if you prefer the API to speak `text`): in `src/agents/base_agent.py` where `result["drafts"] = tools.drafts` (line 145), map each draft `{"text": d["clause_text"], "article_ref": ..., "rationale": ...}`. **Do not** rename the tool arg `clause_text` in `tools.py` — the LLM tool schema (`tools.py:101,105`) depends on it.

**Verify:** run a draft request, confirm clause bodies show and an Arabic draft renders RTL.

---

## P0-B — Confirm the model you're actually running

**Not a temperature bug.** `temperature=0.0` is already the default everywhere (`src/llm_client.py:148`, orchestrator/synthesizer callers). Run-to-run flag variance is structural: weak model + `allow_fallbacks=true` (provider/quant swaps) + autonomous exploration + `AGENT_MAX_STEPS=20` truncation.

**Action (config only, no code logic change):** in `.env`
- `LLM_MODEL=anthropic/claude-sonnet-5` (or `anthropic/claude-sonnet-4-5`) — the single biggest lever for consistency and tool-loop quality.
- `OPENROUTER_ALLOW_FALLBACKS=false` — stop OpenRouter routing the same request to different providers/quantizations. This is already wired through `Settings.extra_body` (`src/llm_client.py:71-74`), so flipping the env var is sufficient.

**Verify:** hit `python -m src.llm_client` smoke test (bottom of that file prints the resolved model) and run one audit twice — flag set should be materially more stable.

---

## P1 — Revise clauses may render blank (same bug class as P0-A)

**Root cause:** same field-name mismatch, revise path.

- Backend stores `{original_clause, revised_clause, article_ref, rationale, quote_match}` — `src/agents/tools.py:169-185`.
- Frontend `Revision` type expects `clause_original` / `clause_revised` — `web/src/api/types.ts:14-19`.
- Frontend reads `rev.clause_original` / `rev.clause_revised` — `web/src/components/ArtifactPanel.tsx:465-466` (and the `RevisionReport` React view — grep `clause_original` to catch every site).

**Fix — match whichever side you chose for P0-A.** Recommended frontend fix:
- `web/src/api/types.ts:14-19` → `clause_original` becomes `original_clause`, `clause_revised` becomes `revised_clause`.
- Update every `rev.clause_original` / `rev.clause_revised` read in `ArtifactPanel.tsx` (at least `:465-466`) to `rev.original_clause` / `rev.revised_clause`.

**Verify:** run a revise request against an audited contract; confirm both original and revised columns populate.

---

## P2 — Seed for reproducibility (nice-to-have, low risk)

Add `seed=42` so identical inputs are more repeatable across runs (works with Sonnet; ignored by providers that don't support it — harmless).

- `src/llm_client.py` — thread a `seed` through. Cleanest: add it to `Settings.extra_body` (line 72-74):
  ```python
  return {"allow_fallbacks": self.allow_fallbacks, "seed": 42}
  ```
  This flows to every `create_completion` call via `extra_body=settings.extra_body` (`:174`). No per-callsite edits needed.

**Verify:** two identical audits produce identical flags (with fallbacks off + Sonnet).

---

## Suggested execution order

1. P0-B + P2 config/one-liner (`.env`, `llm_client.py`) — smallest, unblocks stable demo.
2. P0-A draft field fix.
3. P1 revise field fix (mirror P0-A choice exactly).
4. Rebuild frontend, run one audit / one draft / one revise end-to-end.

Keep it in a worktree; open as a **draft** PR. Each fix is independent — safe to land incrementally.

---

## Out of scope — needs steer before touching

These are real but bigger calls; **do not** do them under demo time pressure without sign-off:

- **Draft assembly.** Even with the field fix, `/draft` emits a bag of isolated clauses, not a contract (no parties/preamble/numbered articles/signatures). Prompt: `src/prompt_templates.py:106-129`. Fix would be a finish-time "assemble" step — a design change, verify separately.
- **`/export/{doc_id}` is a 501 stub** (`api/main.py:424-426`); the download button is client-side print only. DoD may require a real server export.
- **Draft mode exposes all tools** (audit tools like `flag_risk` available while drafting) — check whether `DomainTools.definitions(mode=...)` (`src/agents/tools.py:28`) actually filters by mode; if not, the drafting agent can wander.
- **DOCX/TXT formatting mangled on view** — extracted to flat `whitespace-pre-wrap` text (`ArtifactPanel.tsx:216`); RTL sampled from first 200 chars (`:212`). Recommendation: demo with PDF contracts (original layout preserved via the highlight/render path); treat DOCX/TXT as best-effort.
