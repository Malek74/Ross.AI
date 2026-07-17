# AGENTS.md — Egyptian Civil-Code Contract Auditor

> Build brief for AI coding agents. Read this fully before writing code.
> Hackathon: Bareq × Soil, 17–18 July 2026 · Track 5 (AI that understands Egypt's law) · 2-person team · ~30h.

---

## 1. Project snapshot

We are building an **Egyptian-law compliance auditor**: feed it a contract, and it flags clauses that violate or are unenforceable under the **Egyptian Civil Code (Law 131/1948)**, each flag citing the specific article in **Arabic and English**, with the exact offending quote from the contract.

It is **not** an ungrounded "ask me anything about Egyptian law" chatbot. The scoped, demo-legible product is a document-in / cited-risk-report-out audit engine, plus a grounded legal-chat mode. In chat mode, a specialist answers questions about the submitted document and, when the question is broader, only from articles retrieved from that specialist's own statute corpus. Every legal answer must distinguish the contract facts from the statute and cite its supporting article; it must say when the available document or corpus does not support a definite answer.

**Framing = an AI paralegal.** An orchestrator triages the document and routes it to domain specialists (Civil live in v1; others stubbed), then synthesizes one cited memo. See §2.1. This is a pitch upgrade over a single-domain checker without expanding what must actually work in 30h.

This is a **remix of an existing repo** (`github.com/Malek74/Exhibit-A-I`, an NDA/ContractNLI auditor). We keep its pipeline skeleton and swap the brain and corpus. See §4.

**Value-add (state this in the pitch):** the real work is the Arabic adaptation, the statute-grounded corpus, the domain shift from English NDAs to Civil Code validity, and evidence-grounded citations. Public datasets used are MIT/Apache — attribute them.

---

## 2. Architecture (target)

```
Target contract (PDF/DOCX/TXT)
    │  ingest + Arabic normalization + clause segmentation
    ▼
Clauses or user question + GOAL ("audit this contract under <domain> law and produce a cited risk report; or answer the user's legal question with grounded citations")
    │
    ▼
        SPECIALIST AGENT  — an LLM in a loop, autonomous over its own steps
        repeat:  reason → choose a tool → observe result → decide next → …
        tools:
          • search_statutes(query)  → GraphRAG: vector search → top-k articles,
                                      then graph-expand via cross-reference edges
                                      to pull related articles the query didn't match directly
          • get_article(number)     → fetch one article (to follow cross-references)
          • flag_risk(clause, quote, article, severity, rationale)
                                    → VALIDATES the quote is a real substring + article exists,
                                      else rejects (evidence-integrity enforced here)
          • revise_clause(clause, revision, article_ref, rationale)
                                    → rewrite a flagged clause to comply; cites the governing article
          • draft_clause(topic, article_ref, rationale)
                                    → generate a new clause grounded in retrieved articles
          • validate_draft(clause)  → self-audit a drafted/revised clause against the index
          • export_pdf(document)    → render the final contract as a print-ready PDF
          • finish(summary)         → the agent decides it is done
    │  the playbook is the agent's RUBRIC/knowledge, NOT a hardcoded for-loop over checks
    ▼
Structured JSON report  ──►  synthesizer  ──►  FastAPI  ──►  React UI
                                                              Modes:
                                                                • Audit    — scan contract for loopholes
                                                                • Chat     — ask about specific laws
                                                                • Revise   — fix flagged clauses in-place
                                                                • Draft    — formulate a new contract → PDF
```

---

## 2.1 Multi-agent (paralegal) layer

The product is framed as an **AI paralegal**: a document (or question) comes in, an **orchestrator** decides which bodies of law it implicates, dispatches to the relevant **domain specialists**, and a **synthesizer** merges their findings into one cited memo.

**A "domain specialist" is not a new system** — it is the same audit-and-chat agent (§2) parameterized by `{corpus_index + playbook + prompt_templates}`. Adding a specialist = point it at a different statute set + playbook. This is why multi-agent is an *extension*, not a rewrite. The repo already has `conversation/router.py` (→ intake classifier) and the conversation agent (→ the paralegal you chat with).

```
contract / question
   → Orchestrator (intake): classify implicated domains        [cheap fast model]
   → dispatch to ≤2 specialists from the Registry
        each Specialist = corpus_index + playbook + prompts → cited flags  [strong model]
   → Synthesizer: merge, dedupe, resolve conflicts → one grouped, cited memo
```

**Registry = live + stub.** Only Civil is live in v1; the rest are registered config entries that return "domain recognized, specialist not yet available." The router is real, the roadmap is visible, nothing is faked.

| Specialist | v1 status | Corpus (see §5) |
|---|---|---|
| Civil | **LIVE** | TawasulAI article-level (bilingual) |
| Commercial | **LIVE** | dataflare, filtered by `law_name` |
| Labour | **LIVE** | dataflare, filtered by `law_name` |
| Criminal / Procedure / Personal-status | STUB | dataflare (document-level) |
| Finance / FRA, Tax | STUB (flagship) | data gap — needs sourcing; see §5 |

**Scope discipline:** each *live* specialist needs its own validated playbook + legal sanity-check. Five shallow agents lose to one that works. Build Civil fully (through M1) **before** wrapping it in the orchestrator; add a 2nd live specialist only if the core lands early.

**Routing model:** use a cheap/fast model (e.g. a free `qwen/*` or `google/gemini-3.1-flash`) for intake classification; reserve the strong model for specialist reasoning. One OpenRouter key, chosen per call. Cache each specialist's corpus separately.

### One class, many instances — and one index per domain

A `DomainAgent` is not bespoke per domain; it is the same **agent** (an LLM in a tool-use loop) parameterized by an index + a playbook. Each specialist has two capabilities: it audits a contract and it acts as a domain-bounded legal chatbot. "Different corpus per agent" is literally just a different `index_path`; the agent's *reasoning* is shared, its *data and rubric* differ.

```python
class DomainAgent:
    def __init__(self, name, index_path, playbook_path):
        self.name   = name
        self.tools  = domain_tools(index_path)        # search_statutes/get_article scoped to THIS index,
                                                      #   + flag_risk (validates quote+citation), finish
        self.rubric = load_playbook(playbook_path)    # guidance it reasons WITH — NOT a for-loop

    def run(self, contract):                          # LLM-in-a-loop: autonomous, not scripted
        goal = f"Audit this contract under {self.name} law; flag risks, each with a cited article."
        return agent_loop(goal, contract, self.rubric, self.tools, max_steps=N)

    def answer(self, question, contract=None):        # Same agent and tools; legal-chat mode
        goal = f"Answer this question under {self.name} law with cited articles."
        return agent_loop(goal, contract, self.rubric, self.tools, question=question, max_steps=N)

class StubAgent:
    def __init__(self, name): self.name = name
    def run(self, contract):
        return {"domain": self.name, "status": "recognized_not_available"}

REGISTRY = {
  "civil":      DomainAgent("civil",      "data/index/civil",      "playbooks/civil.yaml"),
  "commercial": DomainAgent("commercial", "data/index/commercial", "playbooks/commercial.yaml"),
  "labour":     DomainAgent("labour",     "data/index/labour",     "playbooks/labour.yaml"),
  "finance":    StubAgent("finance"),
}
```

### Agent, not workflow (the required properties)

- **Goal** — each specialist is handed an objective ("audit under Civil Code, produce a cited report"), not a script.
- **Legal-chat capability** — the same specialist can receive the objective "answer this legal question under Civil Code with cited articles." It independently decides what to retrieve and whether the submitted contract is relevant. It must ground claims in its domain corpus, cite the article used, and state uncertainty rather than inventing an answer.
- **Autonomy** — *it* decides which clauses to probe, what to search for, whether to pull a cross-referenced article, and when it has enough to stop. Control flow emerges from the model, not from Python branching over 15 checks.
- **Tool calls** — it acts only through tools: `search_statutes`, `get_article`, `flag_risk`, `finish`.
- **Not a workflow** — the playbook is **knowledge the agent reasons with**, not a hardcoded loop. (The workflow version — `for check in playbook: retrieve(); classify()` — is exactly what we are *not* building.)
- **Safe without scripting** — autonomy is over *strategy*; grounding is enforced at the *tool boundary*: `flag_risk` rejects any flag whose quote isn't a real substring or whose article doesn't exist, `search_statutes` is scoped to the agent's own index, and a `max_steps` budget bounds runaway loops. Bounded toolset ≠ scripted steps.

**The paralegal (orchestrator) is also an agent:** its goal is a consolidated cited memo; its tools are the specialist agents themselves (`consult(domain)`), plus `finish`. It decides whom to consult — informed by the classifier but free to consult a second specialist if a first surfaces cross-domain issues — then synthesizes. (Sub-agents-as-tools pattern.)


**Build one FAISS index per domain — do NOT dump all domains into one shared store.** Reasons: (1) retrieval quality — a Labour query shouldn't compete with Civil articles for top-k; (2) currency — rebuild one small index when a law changes, not everything; (3) it maps 1:1 to the agent boundary, so there's no cross-domain contamination. Each index is built once by the same `embeddings.py`, fed a different slice.

```
data/index/
├── civil/         # TawasulAI articles → FAISS + metadata + cross-reference graph
│   ├── index.faiss
│   ├── articles.jsonl
│   ├── metadata.json
│   └── graph.json       # nodes = article numbers, edges = cross-references
├── labour/        # dataflare filtered on law_name → chunked → cleaned → FAISS + graph
└── commercial/    # same recipe, different slice
```

**Embedding-consistency rule (bake in now):** every index must be built with the **same** embedding model it is queried with. Simplest for the hackathon: pick one embedding model and use it for all indexes. Mixing models *within* one index is a silent bug.

**Shared vs. per-agent:**
- **Shared (write once):** `embeddings.py`, `arabic_normalize.py`, the `DomainAgent` class, `playbook_mapper.py`, evidence validation, the audit loop, orchestrator, synthesizer.
- **Per-agent (just data):** the FAISS index under `data/index/<domain>/`, the `playbooks/<domain>.yaml`, and optional domain-specific prompt tweaks.

Adding a domain later = build its index + write its playbook + flip its `StubAgent` to `DomainAgent`. No new retrieval or audit code — that is the whole payoff, and the honest version of the "just add a corpus" pitch line.

---

## 2.2 Routing — how the orchestrator picks the agent

Two modes, and the input decides which agent(s) run:

- **Auto (default):** an intake **classifier** (cheap fast model) reads the document/question and returns the implicated domains, ranked by confidence. The orchestrator dispatches the top ≤2 **live** agents; any matched **stub** returns "recognized, not yet available."
- **Manual (override):** the user explicitly selects the specialist(s) — exactly like choosing a model from a dropdown. The orchestrator skips classification and dispatches straight to the chosen agent(s).

The registry entry carries what the classifier needs (a label + a plain-language description of the domain's scope). Adding a domain therefore also teaches the router about it, for free.

```python
# registry.py — metadata the classifier reads
REGISTRY = {
  "civil":  {"agent": DomainAgent("civil","data/index/civil","playbooks/civil.yaml"),
             "live": True,  "label": "Civil Code",
             "description": "Contracts, obligations, capacity, consent, property, civil liability."},
  "labour": {"agent": StubAgent("labour"), "live": False, "label": "Labour",
             "description": "Employment contracts, wages, termination (Labour Law 14/2025)."},
  # commercial, criminal, finance, ...
}

# classifier.py — cheap model, structured JSON out
def classify(text) -> list[dict]:
    choices = [{"domain": k, "description": v["description"]} for k, v in REGISTRY.items()]
    # prompt: "Return the legal domains this text implicates as
    #          [{'domain','confidence'}], choosing only from <choices>."
    return json_parse(cheap_llm(text, choices))   # [{"domain":"civil","confidence":0.9}, ...]

# orchestrator.py
def route(text, mode="auto", agents=None, k=2, threshold=0.5):
    if mode == "manual":
        selected = agents                                        # user picked (dropdown)
    else:
        selected = [d["domain"] for d in classify(text)
                    if d["confidence"] >= threshold][:k]         # auto
    live = [REGISTRY[d]["agent"] for d in selected if REGISTRY[d]["live"]]
    stub = [d for d in selected if not REGISTRY[d]["live"]]
    return {"selected": selected, "live": live, "stubbed": stub}
```

**Two different "routers" — don't conflate them:** `agents/classifier.py` chooses *which specialist* (domain routing); the existing `conversation/router.py` chooses *which retrieval mode within one agent* (graph vs vector vs none). Keep them separate.

**UX:** default to Auto and show the detected domains as chips the user can edit; expose a specialist picker (Auto · Civil · Labour · …) for manual override. Auto is the demo default; manual is the "I know it's a labour matter, just use that agent" path.

---

## 2.3 What makes these agents (not a workflow)

Explicit checklist — every specialist and the paralegal orchestrator must satisfy all four. If any turns into a hardcoded sequence, it has regressed to a workflow and must be fixed.

- **Goal (not steps):** the agent is given an objective and pursues it. Four goal types, same agent loop:
  - *"Audit this contract under {domain} law; flag risks with citations"*
  - *"Answer this legal question about {topic} with cited articles"*
  - *"Revise flagged clauses to comply with {articles}; preserve intent"*
  - *"Draft a {type} contract compliant with Egyptian {domain} law"*
  The playbook is the agent's **rubric/knowledge**, not a hardcoded loop. It can surface issues the playbook never listed.
- **Tool calls:** the agent acts only through tools it chooses to invoke — `search_statutes`, `get_article`, `flag_risk`, `revise_clause`, `draft_clause`, `validate_draft`, `export_pdf`, `finish` for a specialist; `classify`, `consult_specialist`, `synthesize`, `finish` for the orchestrator. No tool call, no effect.
- **Autonomy:** the LLM drives the loop (`reason → pick tool → observe → decide next`). It decides which clauses to probe, when to retrieve articles, whether to revise or flag, whether a draft clause passes self-audit, and when it is done. Control flow is emergent — a revision task retrieves different articles than an audit of the same contract.
- **Not a workflow:** there is no fixed step order. Two different contracts produce two different tool-call traces. A draft task and an audit task over the same domain use different tool sequences. The orchestrator consulting specialists is genuine agent-calls-agent, not a pipeline stage.

**Bounded, not unbounded** (reconciles the earlier "keep it bounded" note): autonomy is over *investigation*; determinism is over *integrity*. Two hard rails — a **max tool-call budget** per agent (terminates on stage) and **`flag_risk` enforcing `validate_quote` + article existence** (the model can explore freely but cannot emit a hallucinated citation). Show the tool-call trace in the demo — it's the proof of agency judges will look for.

---

## 3. Tech stack

- **Backend:** Python, FastAPI, LangChain (already used in source repo).
- **Model gateway:** **OpenRouter** — one key, one OpenAI-compatible endpoint (`https://openrouter.ai/api/v1`) for **both** the reasoning LLM and embeddings. Model choice is runtime config, not a lock-in.
- **Retrieval:** **GraphRAG** — dense multilingual embeddings → FAISS for vector search, plus a cross-reference graph per domain. Vector search finds entry-point articles; graph traversal follows cross-reference edges (`"subject to Article X"`, `"as defined in Article Y"`) for multi-hop retrieval. **Drop the TF-IDF path** in the source repo (weak on Arabic).
- **Embeddings (via OpenRouter):** A/B `qwen/qwen3-embedding-8b` (strong on Arabic) vs `openai/text-embedding-3-large`; keep the better retriever. (Embeddings have no streaming — irrelevant for indexing.)
- **Reasoning LLM (via OpenRouter):** default `anthropic/claude-sonnet-5`, swappable to `openai/*`, `google/*`, `qwen/*` with one param. **Do not fine-tune** in 30h.
- **Frontend:** React (two-pane audit UI).
- **Env:** single `OPENROUTER_API_KEY`. Use the OpenAI SDK pointed at the OpenRouter base URL. Prompt-cache the statute corpus by putting it at the front of the message — provider caching passes through automatically (~90% off cached input on Claude).

```python
# one client for LLM + embeddings
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
chat = client.chat.completions.create(model="anthropic/claude-sonnet-5", messages=[...])
emb  = client.embeddings.create(model="qwen/qwen3-embedding-8b", input=[...])
```

---

## 4. Reuse map (from Exhibit-A-I)

| Source component | Action | Notes |
|---|---|---|
| Pipeline shape (`inference_pipeline.py`) | **Keep** | ingest → check → playbook → structured output. This is the whole spine. |
| `playbook.yaml` + `playbook_mapper.py` | **Keep, repurpose** | The playbook becomes the agent's **rubric** (`playbooks/civil.yaml`, shipped); the severity/action mapping is applied inside the `flag_risk` tool, not by a post-hoc per-check loop. |
| Evidence-span validation / quote integrity / offset correction | **Keep — critical** | This is the anti-hallucination guarantee. Every citation must be a real substring of the contract. |
| `runtrace_writer.py` + schema JSON | **Keep** | Structured, auditable output the UI consumes. |
| `conversation/` (agent, query_reformulator, retrieval_router, context_builder, history_manager) | **Keep structure** | Powers the follow-up chat tab. Repoint retrieval at the new corpus. |
| `graphrag/` (builder, store, retriever, schema) | **Keep — USE** | Cross-reference graph per domain for multi-hop retrieval. Build graph during corpus indexing. |
| QLoRA Llama-3.1-8B fine-tune + `lora-adapters/` | **Cut** | English NDA-specialized; will not do Arabic law. Replace with API model. |
| 17 fixed ContractNLI hypotheses + `contractnli_loader.py` | **Cut / replace** | New loader ingests arbitrary contract files → clauses. Checks now come from the Civil Code playbook. |
| TF-IDF sparse retrieval | **Replace** | → dense multilingual embeddings. |

---

## 4.1 Repo structure changes

Fork `Exhibit-A-I`, then restructure to this target tree. §4 is the module-level keep/cut/replace; this is the concrete filesystem layout.

```
egyptian-contract-auditor/
├── AGENTS.md
├── DECISIONS.md
├── README.md                       # REWRITE for the new project
├── requirements.txt                # UPDATE deps (see below)
├── .env.example                    # NEW: OPENROUTER_API_KEY (one key: LLM + embeddings)
├── playbooks/                      # NEW: one playbook per live domain
│   └── civil.yaml                  # ships (the playbook_egypt_civil.yaml content)
├── data/
│   ├── corpus/                     # NEW: cleaned articles per domain (civil/, labour/, ...)
│   └── index/                      # NEW: one FAISS index per domain (civil/, labour/, ...)
├── demo_contracts/                 # NEW: deliberately-flawed test contracts
├── eval/
│   └── ground_truth.json           # NEW: ~10 contract → expected-flags pairs
├── src/
│   ├── __init__.py
│   ├── audit_pipeline.py           # RENAME of inference_pipeline.py — the audit loop
│   ├── contract_loader.py          # REPLACES contractnli_loader.py — file → clauses
│   ├── corpus_loader.py            # NEW: load + clean the article dataset
│   ├── arabic_normalize.py         # NEW: alef/hamza/taa-marbuta/diacritics/tatweel
│   ├── llm_client.py               # NEW: OpenRouter client (OpenAI SDK) — LLM + embeddings
│   ├── embeddings.py               # NEW: embeddings via OpenRouter + FAISS index
│   ├── evidence_validation.py      # KEEP/EXTRACT: quote-integrity + offset fix
│   ├── playbook_loader.py          # keep
│   ├── playbook_mapper.py          # keep (label bridge)
│   ├── prompt_templates.py         # keep, REWRITE prompts (comply/violate/silent)
│   ├── runtrace_writer.py          # keep
│   ├── runtrace_utils.py           # keep
│   ├── conversation/               # keep — powers the Chat tab; retrieval routing WITHIN an agent
│   │   ├── conversation_agent.py
│   │   ├── query_reformulator.py
│   │   ├── router.py
│   │   ├── context_builder.py
│   │   ├── history_manager.py
│   │   ├── dense_interface.py       # REPLACES vector_interface.py (TF-IDF)
│   │   └── graph_interface.py       # keep — powers GraphRAG retrieval
│   ├── agents/                      # NEW: multi-agent paralegal layer
│   │   ├── orchestrator.py          #   paralegal AGENT: route(auto|manual) + consult specialists
│   │   ├── classifier.py            #   intake domain classifier (auto routing hint, cheap model)
│   │   ├── registry.py              #   live + stub registry (+ domain descriptions)
│   │   ├── base_agent.py            #   DomainAgent + agent_loop (LLM-in-a-loop, max_steps)
│   │   ├── tools.py                 #   search_statutes · get_article · flag_risk(validated) · revise_clause · draft_clause · validate_draft · export_pdf · finish
│   │   ├── civil_agent.py           #   LIVE specialist (rubric + index binding)
│   │   └── synthesizer.py           #   merge / dedupe / conflict → one memo
│   └── graphrag/                    # keep — cross-reference graph builder + retriever
├── api/                             # NEW: FastAPI
│   ├── main.py                      # app + /audit (auto|manual) + /agents + /chat
│   └── schemas.py                   # request/response models
├── web/                             # NEW: React two-pane UI
└── outputs/                         # ARCHIVE old ContractNLI runs; regenerated at runtime
```

**Add**
- `.env.example`, `data/corpus/`, `data/index/`, `demo_contracts/`, `eval/ground_truth.json`
- `src/corpus_loader.py`, `src/arabic_normalize.py`, `src/embeddings.py`, `src/llm_client.py`
- `src/agents/` (orchestrator, classifier, registry, base_agent, tools, civil_agent, synthesizer), `playbooks/`
- `api/` (FastAPI), `web/` (React)

**Rename / replace**
- `inference_pipeline.py` → `audit_pipeline.py`
- `contractnli_loader.py` → `contract_loader.py` (arbitrary file → clauses)
- `conversation/vector_interface.py` (TF-IDF) → `conversation/dense_interface.py`
- `playbook.yaml` → `playbook_egypt_civil.yaml`

**Remove / retire**
- `lora-adapters/` (QLoRA weights), `make_split.py` (fine-tune split — unused)
- `contractnli_loader.py` after porting, old `outputs/*.json` ContractNLI runs
- Stale docs: `exhibit_a_i_architecture.yaml`, `exhibit_ai_ms2_architecture.svg`, `nli_decision_flowchart_*.png` (archive)
- `evaluate_runtraces.py` — ContractNLI-specific; either adapt into `eval/` or remove

**Dependencies (`requirements.txt`)**
- **Add:** `openai` (SDK, pointed at the OpenRouter base URL — covers both LLM and embeddings), `fastapi`, `uvicorn`, `python-multipart`, `datasets`, `faiss-cpu`, `pymupdf` (or `pdfplumber`), `python-docx`.
- **Remove:** the local fine-tune stack — `peft`, `bitsandbytes`, `accelerate`, and `transformers`/`torch` if they were only there for the QLoRA model. No separate embedding SDK needed (OpenRouter serves embeddings).

---

## 5. Data sources (all on Hugging Face)

- **Rule corpus / spine — `TawasulAI/egyptian-law-articles`.** 1,105 rows, article-level, bilingual (`number`, `page`, `text_ar`, `text_en`), JSON ~943KB, essentially the Civil Code. Each article = one citable chunk/node. **Has OCR quirks** (mixed Arabic/Latin numerals, some articles split across pages) — clean on load.
- **Breadth (optional) — `dataflare/egypt-legal-corpus`.** 25M+ tokens, MIT, hierarchical categories, document-level. Use only if you need coverage beyond the Civil Code.
- **Eval + demo questions — `fr3on/eg-legal-instruction-following`.** 4,184 instruction examples (criminal/civil/procedural/personal-status), Apache-2.0. Seed the test set from this.
- **Retrieval sanity check — `HeshamHaroon/ArabicRAGB`.** Arabic RAG benchmark incl. Egyptian dialect.

Load example:
```python
from datasets import load_dataset
articles = load_dataset("TawasulAI/egyptian-law-articles", split="train")
# each row: {"number", "page", "text_ar", "text_en"}
```

### Corpora for the other specialists

**`dataflare/egypt-legal-corpus` is the multi-domain backbone** — 2,434 rows / 25M tokens, MIT, Arabic, parquet. Each row is a whole law with `law_name`, `categories`, `text`, `tokens`. It already holds most major codes, so a specialist's corpus is a **filter on `law_name`** (more reliable than the coarse Arabic `categories`). Two caveats that mean real work per specialist: it is **document-level** (whole law as one blob → you must re-chunk into articles) and has **visible OCR noise** (e.g. stray `دودو`, mangled numerals → clean it). Loading + filtering:

```python
ds = load_dataset("dataflare/egypt-legal-corpus", split="train")
labour = ds.filter(lambda x: "العمل" in x["law_name"])   # then chunk into articles
```

| Domain | Source | Readiness |
|---|---|---|
| Civil | `القانون المدني` (also article-level in TawasulAI) | ✅ best — use TawasulAI |
| Civil procedure / Evidence | `قانون المرافعات`, `قانون الإثبات` | 🟡 doc-level, chunk it |
| Criminal | `قانون العقوبات`, `قانون الإجراءات الجنائية` | 🟡 doc-level |
| Rent / Lease | `قانون الايجارات` | 🟡 doc-level |
| Personal status | `الأحوال الشخصية`, `قانون الخلع`, `قانون الطفل 12/2003` | 🟡 doc-level |
| Labour | filter `قانون العمل` | 🟠 **verify currency** — corpus is Jan 2026; Labour Law **14/2025** must be the version present |
| Commercial / Trade | filter `قانون التجارة` | 🟠 doc-level; confirm it's included |
| Finance / FRA, Tax | not cleanly in the corpus | 🔴 **data gap** — scrape fra.gov.eg / official gazette; highest currency risk → keep **STUB** |

**Cross-domain eval questions:** `fr3on/eg-legal-instruction-following` covers Criminal, Labour, Civil, Administrative, procedural, and personal-status — seed each specialist's test set from it.

**Takeaway for the paralegal roadmap:** Civil (live) and a 2nd specialist from {Labour, Commercial, Criminal} are all **data-ready** via dataflare (segment + chunk + clean). Finance/FRA and Tax are the true gaps — which is exactly why they stay stubs, and why "adding Finance = source a corpus + write a playbook" is an honest pitch line, not a fake one.

---

## 6. Arabic preprocessing (do this before retrieval, or everything downstream degrades)

- Normalize alef/hamza forms, taa marbuta, strip diacritics (tashkeel) and tatweel.
- Clean the dataset's OCR artifacts (numeral normalization; stitch page-split articles by `number`).
- Confirm retrieval works: query "ما الذي يجعل العقد قابلاً للإبطال؟" / "what makes a contract voidable" and verify the capacity/mistake articles come back.

---

## 7. The playbook (checklist)

Ships as **`playbook_egypt_civil.yaml`** — 15 checks across capacity, consent, object/cause, formation, grounded in Civil Code articles.

- Mirrors the source repo's playbook structure; `playbook_mapper.py` ports via the label bridge (§4).
- **3 checks marked `VERIFY_ARTICLE`** (fraud/tadlis, duress/ikrah, unlawful cause) — fill article numbers from the fuller corpus.
- ⚠️ **Draft, not legal advice.** A person with Egyptian-law knowledge must validate before any accuracy claim to judges.

---

## 8. API surface (FastAPI)

- `POST /audit` — body `{contract, mode?: "auto"|"manual", agents?: [domain]}`. In `auto` (default) the orchestrator classifies domains; in `manual` it uses the `agents` the user picked. Returns `{routing: {mode, selected, stubbed}, flags_by_domain: {domain: [{check_id, label, severity, action, evidence_span, article_ref, article_ar, article_en, rationale, confidence}]}}`.
- `GET /agents` — list registry entries `[{domain, label, live}]` so the UI can render the specialist picker.
- `POST /chat` — `{doc_id, question}` → paralegal (conversation agent) answer grounded in the doc + retrieved articles, with citations.
- `POST /revise` — `{doc_id, flag_ids?: [id]}` → agent revises flagged clauses to comply, citing the governing articles. Returns `{revisions: [{clause_original, clause_revised, article_ref, rationale}]}`.
- `POST /draft` — `{contract_type, domain, requirements?}` → agent drafts a new contract grounded in retrieved articles, self-audits each clause. Returns `{clauses: [{text, article_ref, rationale}], warnings: []}`.
- `GET /export/{doc_id}` — render audited/revised/drafted contract as a print-ready PDF.

---

## 9. UI spec (React)

**Full-cycle paralegal UI — not a plain chat clone.**
- **Left:** rendered contract; clauses individually highlightable.
- **Top of the right panel:** a **specialist picker** like a model dropdown — `Auto (detect)` by default, plus explicit choices (Civil · Labour · …) from `GET /agents`. In Auto, show the detected domains as editable chips; manual selection sends `mode:"manual", agents:[…]`.
- **Right, tabbed:**
  - **Flags** — grouped by specialist ("Civil Code — 3 flags", "Labour — 1 flag"), with a "consulted: Civil, Labour" routing line. Each flag shows severity + cited article (AR/EN); clicking it highlights the offending clause on the left and shows the article text.
  - **Chat** — ask the paralegal about specific laws; follow-up Q&A grounded in the doc + articles (calls `/chat`).
  - **Revise** — one-click "fix this clause" per flag, or "revise all flagged" → agent rewrites clauses to comply, showing before/after with cited rationale (calls `/revise`).
  - **Draft** — formulate a new contract from scratch: pick domain + contract type → agent drafts clauses grounded in retrieved articles, self-audits, returns a ready document (calls `/draft`).
  - **Export** — download the audited/revised/drafted contract as a print-ready PDF (calls `/export/{doc_id}`).
- Wire to the chosen model via OpenRouter (default `anthropic/claude-sonnet-5`), swappable.

---

## 10. Milestones (≈30h, 2 people)

- **M0 — Scope lock (Fri PM):** fork/clean repo; decide embeddings + LLM; load article corpus; embed; **retrieval smoke test** passes.
- **M1 — Vertical slice:** one contract → 3–4 checks → structured flags with real quotes + citations (CLI/JSON, ugly is fine).
- **M2 — Full engine:** all 15 checks + evidence-span validation + `POST /audit`.
- **M2.5 — Paralegal layer (stretch, only after M1/M2 land):** wrap the Civil pipeline in `orchestrator + registry + synthesizer`; register other domains as **stubs**; add a **2nd live specialist** (Labour or Commercial) only if time allows.
- **M3 — UI:** React two-pane wired to `/audit`; add `/chat` tab; group Flags by specialist.
- **M4 — Demo (Sat):** 3–5 deliberately-flawed demo contracts; polish; 2-min video; 3-min pitch; buffer for the code freeze at 18:00 sharp.

**Suggested split:** Person A — retrieval + audit loop + API + orchestrator. Person B — UI + demo contracts + eval set + video.

---

## 11. Definition of done (demo acceptance)

- Upload a contract in the browser → receive ≥3 flags, each with a **real quote** from the contract and a **correct article citation** (AR+EN).
- **Zero hallucinated citations** — evidence-span validation passes on every flag.
- The Chat tab answers a follow-up question about the document with a citation.
- The Revise tab rewrites a flagged clause to comply, citing the governing article.
- The Draft tab generates a new contract from a type + domain selection, with each clause grounded in retrieved articles.
- Export delivers a print-ready PDF of the audited/revised/drafted contract.
- Runs end-to-end in the browser; deploy/host target decided (see DECISIONS.md).
- A small hand-checked ground-truth set (~10 contract → expected-flags pairs) exists so accuracy can be stated honestly in Q&A.

---

## 12. Guardrails

- **Legal accuracy is a claim you must defend in Q&A.** Lean on evidence-span validation + the ground-truth set; never assert the tool "knows the law" — it retrieves and cites it.
- **Currency:** Civil Code (1948) is stable. Labour/tax law changed recently (Labour Law 14/2025) — do **not** extend the demo there without the current text.
- **Agentic, but grounded:** autonomy is over *strategy* (what to investigate, retrieve, flag, and when to stop) — not scripted steps. Safety lives at the tool boundary: `flag_risk` validates every citation, `search_statutes` is scoped to the agent's own index, and a `max_steps` budget caps the loop. That is how it stays a real agent without hallucinating law or wandering on stage.
- **OpenRouter demo ops:** pre-load enough credits before pitching (a `402` = out of credits mid-demo); keep prompt logging **off** (don't opt in) for a legal-document tool; set `allow_fallbacks: true` so a provider outage fails over instead of crashing the demo.
