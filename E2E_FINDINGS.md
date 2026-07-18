# E2E Arabic Pipeline Test — Findings Report

**Date:** 18 July 2026 · **Scope:** full pipeline (FastAPI `localhost:8000` → orchestrator → specialists → RAG/GraphRAG → validated output) tested end-to-end in Arabic for: contract audit, contract recommendations (revise), contract generation (draft), and general Egyptian-law questions (chat).

**Test contract:** `contract_1_labour_ar-v2.pdf` (Arabic labour contract, 721 chars extracted).
**Raw responses:** saved per-scenario under the job tmp dir (`audit.json`, `revise.json`, `draft.json`, `chat.json`, `edge_*.json`).

---

## 1. Models tested

| Run | LLM | Classifier | Outcome |
|---|---|---|---|
| 1 | `qwen/qwen3-next-80b-a3b-instruct:free` | `nvidia/nemotron-3-nano-30b-a3b:free` | ❌ All 4 agent calls 429 — model saturated upstream; retry logic didn't match the error text (fixed, see §5) |
| 2 | `nvidia/nemotron-3-super-120b-a12b:free` | same | ⚠️ Audit passed (278s, 3 civil flags); revise hit step limit; draft/chat 429 — free tier can't sustain multi-call agent loops |
| 3 | `google/gemini-2.5-flash-lite` (paid, minimal cost) | same model | ✅ All 9 scenarios HTTP 200; quality issues noted below |

**Conclusion:** free models are usable for single-shot calls (classifier, intent) but not production agent loops — 16 req/min shared pools + upstream saturation break multi-step audits. Production cutover: `anthropic/claude-sonnet-4-5` + `google/gemini-2.5-flash` (restored per `models-config.md`), `AGENT_MAX_STEPS=100`.

---

## 2. Scenario results (run 3, all Arabic, `lang=ar`)

### 2.1 Contract audit — `POST /audit` (21.3s)

**Input:** the labour contract PDF, `mode=auto`.

**Routing:** classifier hint came back empty (see finding F3); the orchestrator itself consulted `labour` + `commercial`.

**Retrieved chunks (labour specialist, `search_statutes`):**
```
('قانون العمل …مادة (155):', vector, 0.483), ('chunk-30', vector, 0.419),
('chunk-30', vector, 0.418), ('chunk-30', vector, 0.412), …   ← duplicates, pre-fix index
```

**Output (text + artifact):** `status: finished`, summary in Arabic; 3 labour flags citing articles **154, 89, 6**, each with a validated `evidence_span` quote from the contract, article text AR, severity, and rationale. Example evidence span carries PDF OCR noise (stray Latin `los` inside the Arabic quote) — see F6.

### 2.2 Contract recommendations — `POST /revise` (6.0s)

**Input:** same contract text, `domain=labour`.
**Output:** `status: step_limit_or_text_response`, **0 structured revisions** — the model answered in prose (the revision text is in `summary`, correctly citing Law 14/2025 and identifying the non-renewal clause) instead of calling `revise_clause`. See F5. On the earlier Nemotron run the same call died against the broken labour index (F2).

### 2.3 Contract generation — `POST /draft` (27.5s)

**Input:** `domain=civil`, `contract_type="عقد إيجار سكني"`, requirements: 1-year term, EGP 5,000/month, 2-month deposit, landlord maintenance duty.

**Retrieved chunks — GraphRAG confirmed working:**
```
('٥٦٣', vector, 0.454), ('599', graph_expansion), ('601', graph_expansion),
('605', graph_expansion), ('607', graph_expansion)      ← cross-reference edges
('571', vector, 0.396), ('564', vector, 0.387), ('567', vector, 0.347)
('888', vector, 0.51)  … + validate_draft self-audit calls against the index
```

**Output (artifact):** `status: finished`, 2 clauses (rent → art. **567**, maintenance → art. **888**) with rationales, each self-audited via `validate_draft`. Summary claims 4 clauses but only 2 passed the tool boundary — duration/deposit clauses were dropped (F7).

### 2.4 General law question — `POST /chat` (7.2s)

**Input:** «ما هي الشروط اللازمة لصحة العقد وفقاً للقانون المدني المصري؟ وما جزاء تخلف كل شرط؟»

**Retrieved chunks (civil):** `('٤٨١', vector, 0.44), ('266', 0.432), ('101', 0.426), ('89', 0.4), ('٥٥٢', 0.302)`

**Output (text):** correct grounded answer — رضا/محل/سبب with مادة 89 cited for consent, and جزاء (قابلية الإبطال/البطلان) per element. Mixed Arabic-Indic vs ASCII article numbering in the civil index (٤٨١ vs 266) noted as F8.

### 2.5 Edge cases (conversational mode, no contract attached)

| Test | Result |
|---|---|
| `/intent` «دقق العقد وطلعلي المخاطر» `has_contract=false` | ⚠️ returned `audit` — the prompt rule "audit impossible without contract" was **ignored** (F4) |
| `/intent` "audit my contract please" `has_contract=false` | ⚠️ same — returned `audit` |
| `/chat` «قم بتدقيق العقد وبيان البنود المخالفة» no contract | ⚠️ consulted civil+commercial, 0 flags, but summary said **"العقد قيد المراجعة لا يحتوي على مخالفات"** — implies a contract was reviewed when none exists (F4). Tool boundary held (no fabricated flags). |
| `/chat` Egyptian dialect «لو صاحب الشغل رفدني من غير سبب ايه حقوقي؟» | ✅ routed to labour, grounded answer on arbitrary-dismissal rights (notice, compensation, 7-day settlement) |

---

## 3. Findings

- **F1 — Free models can't run production agent loops.** Upstream saturation + shared rate pools. Fixed by production models; retry hardening in §5 keeps free models viable for dev.
- **F2 — Labour index was unusable (root cause of "labour specialist returns zero flags").** 328/670 rows numbered `chunk-N` (article regex anchored on newlines that OCR text doesn't have), 65 rows contaminated from other laws (civil/insurance/constitution/penal), the same repealed Law 12/2003 indexed twice (duplicate hits), and the current Law 14/2025 absent (its download URL 404s). `flag_risk`/`get_article` validate against article numbers → the agent could never emit a validated labour citation → burned all 40 steps → empty result. **Fixed — see §5.**
- **F3 — Domain classifier returns no hints on flash-lite** (`classification: []` on every run; worked on Nemotron: labour 0.94). Orchestrator routing still worked via its own reasoning. Verify on the production classifier; consider the embedding-similarity fallback discussed (query each domain FAISS index, rank by top-hit score — no extra LLM call).
- **F4 — No-contract conversational path misbehaves.** `/intent` ignores `has_contract=false` and still returns `audit`; `/chat` phrasing implies a contract was reviewed when none was attached. Recommendation: enforce the gate in code, not the prompt (if `intent∈{audit,revise}` and `!has_contract` → coerce to `chat` and have the UI prompt for upload), and add one system-prompt line for chat mode: "if no contract is provided, say so explicitly and ask for it."
- **F5 — Revise returns prose instead of structured revisions** on flash-lite (`step_limit_or_text_response`, empty `revisions[]`). Expect production model to call `revise_clause` properly; retest at cutover.
- **F6 — Evidence spans inherit PDF OCR noise** (stray Latin fragments inside Arabic quotes). Quote validation still matches; highlight fuzzy matching (0.55 word-bag threshold) tolerates it. Cosmetic for the report UI.
- **F7 — Draft emits fewer clauses than its summary claims** (2 of 4; duration/deposit dropped when `draft_clause` article refs failed validation). Retest on production model.
- **F8 — Civil index mixes Arabic-Indic and ASCII article numbers** (`٤٨١` vs `266`). **Fixed:** all 1,097 `number` fields normalized in place (572 rewritten; metadata-only, no re-embed). 8 residual number collisions remain from duplicate source rows (harmless: `get_article` returns the first match).
- **F9 — Commercial is a confirmed DATA GAP, worse than F2.** Rebuild ran with the fixed loader and produced only **73 rows, 61 of them un-numbered fragments** — because `dataflare` does **not contain the Commercial Code (قانون التجارة 17/1999)** at all, only encyclopedia-style mini-entries, and tarekys5 has **zero** commercial rows. The user-supplied `data/corpus/commercial/law-17-1999.pdf` has a text layer with **broken font character maps** — all 135 pages extract as mojibake — so it needs Arabic OCR or a different text-layer source. Until then the commercial specialist is effectively stub-quality; treat its audits as unreliable.
- **F10 — Weak models misuse the agent loop in draft mode** (observed on flash-lite): one run crawled the corpus with **128 sequential `get_article` calls**, the next made **zero** tool calls and wrote the contract as plain text. Mitigated with a hard 20-lookup budget at the tool boundary, an explicit retrieval-budget prompt rule, and a plain-text salvage path (see §5).

---

## 4. Frontend bugs found & fixed (flagged during review)

- **Draft field mismatch:** backend emitted `clause_text`, frontend (`types.ts:22`, `ArtifactPanel.tsx` render + print/export path) reads `clause.text` → clause bodies rendered as `undefined`. Backend now emits `text` (matches AGENTS.md §8 spec). Verified end-to-end in run 3.
- **Revise field mismatch (same class of bug):** backend emitted `original_clause`/`revised_clause`; frontend + AGENTS.md §8 use `clause_original`/`clause_revised` — this is why the revision card showed the law citation under the "الأصلي" column. Backend keys fixed to the spec.
- **PDF viewer re-render loop:** `flags={Object.values(...).flat()}` created a new array identity every render; `PdfContract`'s `useEffect([file, flags])` re-POSTed `/highlight` and recycled the blob URL on every parent re-render. Fixed with a `useMemo` (`allFlags`).

---

## 5. Fixes applied in this session

| Area | Fix |
|---|---|
| `src/llm_client.py` | Retry now also matches upstream "temporarily rate-limited / retry shortly" 429s (previously failed instantly) |
| `src/corpus_loader.py` | Article-header regex accepts any-whitespace boundaries + requires a header separator (kills `chunk-N` fallback and prose cross-ref false splits) |
| `src/corpus_loader.py` | New gazette extractor for **Labour Law 14/2025** (`data/corpus/labour/labour_law_14_2025.pdf`, official-gazette text via manshurat.org): NFKC ligature folding + digit-reversal disambiguation by walking the ascending article sequence → **264 statute articles** (gap: block 249–266, differently formatted headers) |
| `src/corpus_loader.py` | tarekys5 Q&A rows now filtered by **law title** (removes cross-domain contamination), real article number parsed from the title, deduped to one row per article, `qa-N` prefix when the statute row exists |
| Labour build (`build_corpus.py` + CLI) | Repealed Law 12/2003 dropped; index rebuilt: **557 rows (264 statute + 293 Q&A), 0 chunk-ids, 0 duplicates**; `get_article("89"/"154"/"6"/"120")` all resolve; retrieval smoke test passes |
| `src/agents/tools.py` | Draft clause key `clause_text` → `text` |
| `web/` | `useMemo` flags fix + `index` passed to `/highlight` (typecheck clean) |
| `api/main.py` `/highlight` | Overlapping flags: highest severity wins the color, others merge; **numbered badge** (breach number, severity-colored disc) beside each highlight on the original PDF; opacity raised to 0.55 for visibility. Verified on `contract-test-2.pdf` (screenshot-checked: merged red highlight with badges 1+2, separate blue with badge 3) |
| `api/main.py` `/intent` | No-contract gate enforced in **code**: `audit`/`revise` intents are coerced to `chat` when `has_contract=false` (closes F4's intent half) |
| `api/main.py` `/apply-revisions` (new) | Applies accepted revisions to the contract text and returns a print-ready PDF (pymupdf `Story` — paginated, Arabic bidi-shaped). Verified: Arabic contract rendered RTL with the revised clause applied (`X-Applied-Count` header) |
| `web/` Revision artifact | Report tab now renders a proper 3-column changes table — **الأصلي / المعدّل / السند القانوني** (original clause, revised clause, cited article + rationale), RTL-aware; العقد tab shows the **revised contract as a generated PDF** via `/apply-revisions` |
| Civil index (F8) | Article numbers numeral-normalized in place (1,097 rows, no re-embed); graph node ids already ASCII |
| Commercial rebuild (F9) | Rebuilt with the fixed loader — exposed the data gap above; old 180-row corpus backed up in job tmp |
| `src/agents/classifier.py` (F3) | Embedding-similarity fallback implemented but **gated off** (`CLASSIFIER_EMBED_FALLBACK=true` to enable): testing showed raw cosine scores are not comparable across heterogeneous indexes (Q&A rows outscore statutes on any question), so the ranking misroutes — needs per-domain calibration first |
| Draft = full contract document | `SPECIALIST_USER_DRAFT` now demands a complete document in the response language (title, تمهيد with party placeholders, numbered clauses, signatures); `base_agent` assembles `document` from recorded clauses, or salvages a plain-text draft with a `draft_not_grounded` warning; `max_tokens` 8192 for draft/revise; `get_article` capped at 20 lookups/run (F10 rail) |
| Draft rendering | `/apply-revisions` renders markdown bold properly (no literal `**`), HTML-escaped; frontend shows the drafted contract as a PDF in the العقد tab (reuses the revised-PDF path) and fits pages to width (`#view=FitH`). Verified: 2-page RTL rental contract with title/preamble/5 clauses/signatures |
| `.env` | Reverted to `google/gemini-2.5-flash-lite` (both roles) for cheap user testing; switch to `models-config.md` production models when ready — `AGENT_MAX_STEPS=100` |

**Note:** the scanned `Egyptian Labor Law no. 14 of 2025.pdf` in `data/corpus/labour/` has no text layer (166 image pages) — kept as reference only; the gazette text PDF is the machine-readable source.

## 6. Remaining before demo

1. **Source a readable Commercial Code text** (F9) — the current PDF needs Arabic OCR or a replacement with working font maps; until then consider demoting commercial to stub in the registry.
2. Retest revise/draft structured output on the production model (F5, F7 — the plain-text salvage covers weak models, but grounded citations need the strong model).
3. Fill the 249–266 article gap in Labour 14/2025 (penalties chapter formatting) or confirm Q&A coverage suffices.
4. Calibrate the classifier embedding fallback (F3) if wanted — per-domain score normalization — or leave it gated off.
5. Re-run this suite once on production models before the pitch (OpenRouter credits pre-loaded, `allow_fallbacks` on).
