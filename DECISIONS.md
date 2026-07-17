# DECISIONS.md — Egyptian Civil-Code Contract Auditor

> Running log of what's decided, why, and what's still open (with options).
> Bareq × Soil hackathon · Track 5 · last updated during planning.

---

## Part A — Decisions made

| # | Decision | Rationale |
|---|---|---|
| 1 | **Track 5** — AI that understands Egypt's law | High ceiling; best fit for the team's RAG / document-reasoning strengths. |
| 2 | **Product = Egyptian-law compliance auditor**, not open legal Q&A | Narrow and demo-legible; a judge grasps the value in ~30 seconds. |
| 3 | **Scope to Civil Code contract validity** | Stable 1948 law, cleanest available data, maximum reuse of the existing repo. |
| 4 | **Remix `Exhibit-A-I`**, not build from scratch | Its pipeline/playbook/evidence-validation skeleton is a genuine head start. |
| 5 | **Cut the QLoRA fine-tune + the 17 fixed hypotheses** | English NDA-specialized; won't transfer to Arabic Civil Code. |
| 6 | **No fine-tuning** in the hackathon | No Arabic-law training set + no time; API + RAG is the right path in 30h. |
| 7 | **Retrieval = dense multilingual embeddings + FAISS**; drop TF-IDF | Sparse retrieval is weak on Arabic. |
| 8 | **Corpus spine = `TawasulAI/egyptian-law-articles`** | Article-level, bilingual, citable per article — ideal RAG/GraphRAG spine. |
| 9 | **Start with plain vector RAG**; GraphRAG is a stretch | Reliable demo first; article cross-reference edges only if core lands early. |
| 10 | **Checklist v1 = `playbook_egypt_civil.yaml`** (15 checks) | Grounded in real Civil Code articles; mirrors the repo's playbook so the mapper ports. |
| 11 | **UI = two-pane audit view** (doc + Flags/Chat tabs), not a plain chat clone | Showcases the audit engine, not just a chatbot; reuses the React strength. |
| 12 | **Demo on Civil Code only; treat labour/tax as out of scope** | Those changed recently (Labour Law 14/2025) — a moving target. |
| 13 | **Model gateway = OpenRouter** (one key for LLM + embeddings) | Collapses the old B1/B2 into runtime config; lets us A/B models without code changes; caching + fallbacks pass through. No inference markup (5.5% credit-purchase fee only). |
| 14 | **Multi-agent "paralegal" framing** — orchestrator + Civil specialist (live) + synthesizer; other domains stubbed | Stronger pitch than a single-domain checker; a specialist is just `corpus + playbook + prompts`, so it extends the existing pipeline. Built as a **post-M1 layer**, not from scratch. |
| 15 | **One FAISS index per domain** (`data/index/<domain>/`), not a shared store with a metadata filter | Better retrieval (no cross-domain competition for top-k); rebuild one small index when a law changes; maps 1:1 to the agent boundary. Same `DomainAgent` class, different `index_path`. |
| 16 | **One embedding model system-wide** — every index built and queried with the same model | Vectors across indexes must be comparable; mixing models within an index is a silent bug. B1's A/B just selects which single model that is. |
| 17 | **Routing = auto classifier (default) + manual override** | Orchestrator auto-detects domains via a cheap classifier, but the user can pick a specialist directly (like choosing a model). Domain routing (`classifier.py`) is separate from retrieval routing (`conversation/router.py`). |
| 18 | **Specialists + orchestrator are true agents** — goal + tool calls + autonomous loop, NOT a fixed pipeline | The hackathon is judged on agency; a scripted `for check in playbook` loop would fail Q&A. Agent chooses its own tool-call path; bounded by a `max_steps` budget and a `flag_risk`→`validate_quote` integrity gate. Playbook is the rubric, not the control flow. |

---

## Part B — Open decisions (with options)

### B1. Which models to default to? *(now runtime config via OpenRouter — decision #13)*

No longer a lock-in. Set a default, keep the shortlist, A/B them during M0–M1 with a param change. Costs are per **million tokens (in/out)**, current 15 Jul 2026; pass-through rates (OpenRouter adds no inference markup, ~5.5% credit-purchase fee only). Pick for **Arabic reasoning + citation reliability**, not price — hackathon spend is single-digit dollars.

**Reasoning LLM — default `anthropic/claude-sonnet-5`:**

| OpenRouter model | Cost (in/out) | For us |
|---|---|---|
| `anthropic/claude-sonnet-5` ⟵ default | $2/$10 intro (→ $3/$15 on 1 Sep) | Strong reasoning + Arabic. Good default brain. |
| `anthropic/claude-opus-4.8` | $5/$25 | Reserve for the hardest legal reasoning. |
| `openai/gpt-5.6` | ~$2.50/$15 | Comparable; solid Arabic. |
| `google/gemini-3.1-pro` | ~$2/$12 | Free tier available. |
| `qwen/*`, `deepseek/*` (free variants) | $0 (rate-limited) | Prototype/testing before spending. |

**Embeddings — A/B once, then use that ONE model for every index (decision #16):**
- `qwen/qwen3-embedding-8b` — strong multilingual/Arabic.
- `openai/text-embedding-3-large` — validated on Arabic legal retrieval (ALARB).
- Pick the better retriever during M0 and lock it system-wide; do **not** mix models across domains. (Both via the same OpenRouter key — the earlier "need a separate embeddings provider" caveat no longer applies.)

**Why frontier over Arabic-specialized brains:** grounded citations (our evidence-span validation) matter more than native Arabic fluency.

### B2. GraphRAG or vector-only?
- **Vector-only (default):** reliable, fast, demo-ready.
- **GraphRAG (stretch):** add article cross-reference / repeal edges for multi-hop reasoning. Repo already has scaffolding. Only if M0–M2 finish early.

### B2b. Which 2nd specialist to make live (if time allows after M1/M2)?
- **Labour** — high real-world relevance; data present in dataflare, **but** must use Labour Law **14/2025** (verify the corpus has the current version, not the old 12/2003). Currency risk.
- **Commercial / Trade** — shares the contract-review shape; likely in dataflare; lower currency risk than labour.
- **Recommendation:** Commercial if you want the safest demo; Labour if you want the more relatable one. **Do not** pick Finance/Tax as the 2nd live agent — corpus is a data gap and currency risk is highest; keep it the flagship **stub**. (Everything Criminal/Procedure/Personal-status = stub for v1.)

### B3. What to build first after setup?
- **Two-pane UI** — visible progress, judge-facing.
- **Deliberately-flawed demo contracts** — guarantees the tool visibly catches things on stage.
- (Either is reasonable; the flawed contracts de-risk the demo, the UI de-risks the impression.)

### B4. Hosting / deploy for the demo
- Options: run locally + screen-share; deploy frontend (Vercel/Netlify) + backend (Render/Railway/Fly). **Undecided** — pick by M3 so the 2-min video shows it running.

### B5. Who validates the checklist legally?
- Needs a person with Egyptian-law knowledge to sanity-check before any accuracy claim. **Owner unassigned.**

### B6. Task split between teammates
- Proposed: A = retrieval + audit + API; B = UI + demo contracts + eval + video. **Confirm.**

---

## Part C — Risks & caveats

- **Legal accuracy** — judges will probe hallucination. Mitigation: evidence-span validation (citations are real quotes) + a ~10-item ground-truth set. Never claim the tool "knows" the law; it retrieves and cites it.
- **Corpus OCR quirks** — mixed numerals, page-split articles in the spine dataset. Clean on load.
- **Single-statute breadth** — the clean article-level set is essentially the Civil Code. Fine for a scoped demo; don't overclaim coverage.
- **Currency** — datasets are 2025-vintage; Civil Code stable, labour/tax not. Stay on Civil Code.
- **Arabic retrieval quality** — confirm with the smoke test before building on top.
- **Live-demo reliability** — bounded audit loop; avoid open-ended agent autonomy that can break on stage.
- **Multi-domain corpus (per specialist)** — dataflare covers most codes but is **document-level with OCR noise**, so each new specialist needs re-chunking into articles + cleaning. Finance/FRA and Tax are **data gaps** (not cleanly in HF) → stubs only. Every *live* specialist also needs its **own validated playbook + legal sanity-check** — this legal-validation cost, not code, is what caps how many domains go live.

---

## Part D — Attribution / licensing

- `TawasulAI/egyptian-law-articles`, `dataflare/egypt-legal-corpus` (MIT), `fr3on/eg-legal-instruction-following` (Apache-2.0) — attribute in the repo. Original legal texts are public domain.
- We fork our own prior repo (`Exhibit-A-I`); the value-add is the Arabic adaptation, statute corpus, domain shift, and citation grounding.