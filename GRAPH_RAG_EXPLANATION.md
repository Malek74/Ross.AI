# Graph RAG Explanation

## Overview

**Graph RAG** = **Graph-enhanced Retrieval-Augmented Generation**

Our system combines two retrieval strategies:
1. **Vector Search** (FAISS) — semantic similarity search over article embeddings
2. **Graph Expansion** — follow cross-reference edges to discover related articles

Result: More comprehensive, multi-hop legal knowledge retrieval.

---

## The Two-Layer Retrieval Pipeline

```
User Query
    ↓
[Layer 1] Vector Search (FAISS)
    → Returns top-k semantically similar articles
    ↓
[Layer 2] Graph Expansion (BFS)
    → Follows cross-reference edges from seed articles
    → Discovers related articles the query didn't directly match
    ↓
Merged Results
    (Vector hits first, then graph-expanded articles)
```

---

## Key Components

### 1. **FAISS Index** (`data/index/<domain>/index.faiss`)
- Pre-built semantic search index for each domain (Civil, Labour, Commercial)
- Stores normalized embedding vectors for all articles
- Enables fast vector similarity search
- Uses L2-normalized inner product (= cosine similarity)

### 2. **Parallel Articles Store** (`data/index/<domain>/articles.jsonl`)
- Keeps articles in exact same order as FAISS index rows
- Stores full article text (Arabic + English), number, metadata
- Used to fetch and return article details after index search

### 3. **Cross-Reference Graph** (`data/index/<domain>/graph.json`)
- **Nodes** = article numbers (e.g., "42", "131", "123")
- **Edges** = references between articles (source → target)
- Built by parsing legal phrases in article text:
  - Arabic: `المادة 123` / `المواد 120 إلى 125`
  - English: `Article 123` / `Articles 120 to 125`

Example graph.json:
```json
{
  "nodes": ["1", "2", "42", "123", "131", ...],
  "edges": [
    {"source": "42", "target": "131"},    // Article 42 references Article 131
    {"source": "131", "target": "42"},    // Bidirectional reference
    {"source": "123", "target": "120"}    // Article 123 references Article 120
  ],
  "stats": {
    "node_count": 1105,
    "edge_count": 2547,
    "most_referenced": [["131", 47], ["42", 32], ...]
  }
}
```

### 4. **Metadata Lock** (`data/index/<domain>/metadata.json`)
- Stores embedding model name, dimensions, article count
- Enforces consistency: all indexes must use the SAME embedding model
- Mismatch raises error (prevents silent retrieval degradation)

```json
{
  "model": "qwen/qwen3-embedding-8b",
  "dim": 1024,
  "count": 1105,
  "built_at": "2026-07-18T12:34:56Z",
  "source": "tawasul_ai"
}
```

---

## How Graph Expansion Works

### Step-by-Step Example

**Query:** "ما الذي يجعل العقد قابلاً للإبطال؟" (What makes a contract voidable?)

```
1. Vector Search (top_k=5)
   → Returns: [Article 123, Article 131, Article 42, Article 120, Article 121]

2. Graph Seed Selection (expand_top=3)
   → Use top 3 as graph entry points: [Article 123, Article 131, Article 42]

3. Graph Expansion (max_hops=1, max_expanded=4)
   Article 123 → neighbors: [Article 120, Article 124, Article 125]
   Article 131 → neighbors: [Article 42, Article 132]
   Article 42  → neighbors: [Article 131, Article 43]
   
   Discovered (deduped): [Article 120, Article 124, Article 125, Article 132, Article 43]
   Capped at max_expanded=4: [Article 120, Article 124, Article 125, Article 132]

4. Final Result Merge
   Vector hits (5) + graph-expanded (4) = 9 total articles
   (Vector hits ranked first, then graph-expanded appended)
```

### BFS (Breadth-First Search) Algorithm

- Starts from seed article numbers
- Explores outgoing + incoming edges (both directions)
- Tracks visited to avoid cycles
- Stops when:
  - Max hops reached (depth limit)
  - Max expanded cap hit (result limit)
  - No more neighbors to explore

---

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `top_k` | 5 | How many articles from initial vector search |
| `expand_top` | 3 | How many of those to use as graph seeds |
| `max_hops` | 1 | Graph traversal depth (1 = direct neighbors only) |
| `max_expanded` | 4 | Maximum new articles to discover via graph |

**Tuning:**
- Higher `max_hops` → deeper graph exploration (more comprehensive, slower)
- Higher `max_expanded` → more results (potentially noisier)
- Smaller `expand_top` → fewer graph entry points (faster)

---

## The Three Domains

Each domain has its own independent index + graph:

| Domain | Articles | Edges | Source |
|---|---|---|---|
| **Civil** | 1,105 | ~2,500 | TawasulAI article-level |
| **Labour** | ~330 | ~1,200 | dataflare (filtered) |
| **Commercial** | ~250 | ~900 | dataflare (filtered) |

**Separation benefits:**
- Civil queries don't compete with Labour queries
- Rebuild one domain without re-indexing others
- Clear domain boundaries for specialists

---

## Implementation Files

| File | Role |
|---|---|
| `src/graphrag/builder.py` | Extract cross-references → build graph.json |
| `src/graphrag/retriever.py` | GraphExpandedRetriever class (vector + graph search) |
| `src/embeddings.py` | DomainIndex class (FAISS loading + search) |
| `src/agents/tools.py` | DomainTools.search_statutes() calls retriever |
| `data/index/<domain>/` | Built indexes, graphs, metadata |

---

## Why Graph RAG?

### Problem It Solves
- **Vector search alone** finds semantically similar articles, but misses related ones
- Example: Query about "contract formation" may not directly match Article 131 (capacity) unless the embeddings are perfect
- **Graph expansion** follows legal cross-references, surfacing implicitly related law

### Specific Example
```
Query: "ما هي شروط صحة العقد؟" (What are the requirements for a valid contract?)

Without graph:
  → Returns: Article 123 (capacity), Article 120 (consent), Article 125 (object)

With graph expansion:
  → Returns the above + Article 131 (defects of consent), Article 42 (legal persons)
    because they're cross-referenced BY/FROM the initial results
  → More complete picture of contract validity
```

---

## Data Flow (End-to-End)

```
Contract Auditor Agent
    ↓
Calls: search_statutes("عقد قابل للإبطال")
    ↓
DomainTools.search_statutes()
    ↓
GraphExpandedRetriever.search()
    ├─→ DomainIndex.search() [vector search via FAISS]
    ├─→ CrossReferenceGraph.expand() [BFS on edges]
    └─→ DomainIndex.get_article() [fetch expanded articles]
    ↓
Returns merged list: [Article 123 (score 0.92), Article 131 (score 0.87), ...]
    ↓
Agent flags risks with real article citations
```

---

## Known Limitations

⚠️ **OCR Artifacts in Graph Nodes**
- Some nodes like `"None"`, `"Article1022"`, `"1104 (3)"` are parsing errors
- Should be cleaned during corpus ingestion
- Doesn't break retrieval, but clutters the graph

⚠️ **Graph Dependency**
- If graph.json is missing or corrupted, retriever falls back to vector-only search
- Graph expansion is optional, not mandatory

---

## Summary

**Graph RAG = Smart Multi-Hop Retrieval**

1. Vector search finds semantically closest articles
2. Graph expansion follows legal citations to nearby articles
3. Results merged: comprehensive, grounded in both similarity AND legal structure
4. Each domain has independent index + graph
5. Used automatically by all domain agents via `search_statutes()` tool
