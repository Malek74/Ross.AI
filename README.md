egyptian-contract-auditor/
├── AGENTS.md
├── DECISIONS.md
├── README.md                       # rewrite for the new project
├── requirements.txt                # openai SDK, fastapi, datasets, faiss-cpu, pymupdf, python-docx…
├── .env.example                    # OPENROUTER_API_KEY (one key: LLM + embeddings)
├── playbooks/                      # one playbook per LIVE domain
│   └── civil.yaml                  # ships (the playbook_egypt_civil.yaml content)
├── data/
│   ├── corpus/                     # cleaned articles per domain — civil/, labour/, …
│   └── index/                      # one FAISS index per domain — civil/, labour/, …
├── demo_contracts/                 # deliberately-flawed test contracts
├── eval/
│   └── ground_truth.json           # ~10 contract → expected-flags pairs
├── src/
│   ├── audit_pipeline.py           # (was inference_pipeline.py) the audit loop
│   ├── contract_loader.py          # (was contractnli_loader.py) file → clauses
│   ├── corpus_loader.py            # load + clean an article dataset
│   ├── arabic_normalize.py         # alef/hamza/taa-marbuta/diacritics/tatweel
│   ├── llm_client.py               # OpenRouter client (OpenAI SDK) — LLM + embeddings
│   ├── embeddings.py               # embeddings via OpenRouter → per-domain FAISS
│   ├── evidence_validation.py      # quote-integrity + offset fix (anti-hallucination)
│   ├── playbook_loader.py          # keep
│   ├── playbook_mapper.py          # keep (label bridge)
│   ├── prompt_templates.py         # rewrite prompts (comply/violate/silent)
│   ├── runtrace_writer.py          # keep
│   ├── runtrace_utils.py           # keep
│   ├── conversation/               # Chat tab; retrieval routing WITHIN an agent
│   │   ├── conversation_agent.py
│   │   ├── query_reformulator.py
│   │   ├── router.py               # graph vs vector vs none (NOT domain routing)
│   │   ├── context_builder.py
│   │   ├── history_manager.py
│   │   ├── dense_interface.py      # (was vector_interface.py TF-IDF)
│   │   └── graph_interface.py      # stretch
│   ├── agents/                     # multi-agent paralegal layer
│   │   ├── orchestrator.py         # route(mode=auto|manual) → dispatch ≤2 specialists
│   │   ├── classifier.py           # intake DOMAIN classifier (auto routing, cheap model)
│   │   ├── registry.py             # live + stub registry (+ domain descriptions)
│   │   ├── base_agent.py           # DomainAgent = index_path + playbook + prompts
│   │   ├── civil_agent.py          # LIVE specialist
│   │   └── synthesizer.py          # merge / dedupe / conflict → one memo
│   └── graphrag/                   # stretch only
├── api/                            # FastAPI: /audit (auto|manual) + /agents + /chat
│   ├── main.py
│   └── schemas.py
├── web/                            # React two-pane UI (specialist picker + Flags/Chat)
└── outputs/                        # archive old ContractNLI runs; regenerated at runtime