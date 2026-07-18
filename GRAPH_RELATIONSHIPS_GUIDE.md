# Graph Relationships Guide

## What Are Graph Relationships?

The cross-reference graphs in your project capture **legal citation dependencies** between articles. When one article explicitly references another, an **edge** (directed link) is created from the source to the target article.

---

## Types of Relationships Extracted

### 1. **Explicit Legal References** (Primary Type)

Articles cite other articles using standard legal language. The extraction detects these patterns:

#### Arabic Patterns
```
المادة 123              → "Article 123"
المادتين 123 و 124     → "Articles 123 and 124"
المواد 120 إلى 125     → "Articles 120 to 125"
بموجب المادة 42         → "Pursuant to Article 42"
وفقاً للمادة 131       → "In accordance with Article 131"
طبقاً لأحكام المادة X → "In compliance with Article X"
```

#### English Patterns
```
Article 42             → Direct reference
Articles 42 and 123    → Multiple articles
Articles 42 to 50      → Range reference
```

### 2. **Reference Context Detection**

The system validates references by checking **legal keywords** in the surrounding text (40 characters before the number):

**Arabic Keywords Recognized:**
- `المادة` — "the article"
- `المادتين` — "the two articles"
- `المواد` — "the articles"
- `مادة` — "article"
- `بموجب` — "pursuant to / by virtue of"
- `أحكام` — "provisions"
- `وفقاً` — "in accordance with"
- `طبقاً` — "in compliance with"

**Result:** A number is only added as a reference if these keywords appear nearby, reducing false positives (e.g., dates or measurements).

### 3. **Direction of Relationships**

All edges are **directional** (one-way):

```
Article 123 → Article 42
```

This means:
- **Article 123** (source) cites/references **Article 42** (target)
- Not necessarily the inverse (unless Article 42 also cites Article 123)
- Enables multi-hop graph traversal: "What does this article depend on?"

### 4. **Relationship Patterns by Domain**

Each domain has distinct reference patterns:

#### **Civil Code (1,105 articles, ~2,500 edges)**
- **High-density hubs:** Articles 42 (capacity), 131 (defects of consent), 120-125 (contract formation)
- **Cascading references:** Article 14 references Articles 12-13; those reference Articles 11, etc.
- **Example:** Article 123 (essential mistakes) → Articles 120, 131, 42 (related validity issues)

#### **Labour Law (dataflare slice, ~330 articles, ~1,200 edges)**
- **Chunked structure:** Articles grouped by topic (employment contract, wages, termination)
- **Fewer cross-references:** More contained within subsections
- **Example:** Article 42 (wages) → Articles 38-40 (related wage provisions)

#### **Commercial Law (~250 articles, ~900 edges)**
- **Sectional references:** Trade articles cite general principles
- **Example:** Article 252 (partnership) → Articles 240-251 (company formation prerequisites)

---

## How Relationships Enable Retrieval

### Vector Search Alone

```
Query: "ما شروط صحة العقد؟" (What are the conditions for contract validity?)
│
└─► Vector Search (FAISS)
    ├─ Article 123 (essential mistakes) — score 0.92
    ├─ Article 120 (mistake definition) — score 0.87
    └─ Article 42 (capacity) — score 0.78
```

### With Graph Expansion (Multi-Hop)

```
Query: "ما شروط صحة العقد؟"
│
├─► Vector Search (top-3 seed articles)
│   ├─ Article 123 (score 0.92) ◄──── seed
│   ├─ Article 120 (score 0.87) ◄──── seed
│   └─ Article 42 (score 0.78) ◄──── seed
│
├─► Graph Expansion (BFS from seeds)
│   Article 123 → edges → [Article 121, Article 124, Article 125]
│   Article 120 → edges → [Article 121, Article 22]
│   Article 42  → edges → [Article 131, Article 43, Article 44]
│
└─► Merged Results (9 total)
    Vector hits (3) + graph-expanded (4-6 new) = richer context
```

**Benefit:** User gets not just similar articles, but related legal concepts they didn't explicitly search for.

---

## Relationship Characteristics

### **Properties of Each Edge**

```json
{
  "source": "42",
  "target": "131"
}
```

| Property | Value | Meaning |
|---|---|---|
| `source` | Article number | Article that is **doing the citing** |
| `target` | Article number | Article being **cited/referenced** |
| Direction | one-way | Asymmetric (A→B ≠ B→A) |
| Semantics | "citation" | Legal precedence/dependency |
| Weight | implicit | All edges equally weighted (no strength measure) |

### **What Relationships Tell You**

1. **Article A → Article B** means: A relies on, is subject to, or builds upon B
2. **High in-degree** (many edges → Article X) = Central/foundational article
3. **High out-degree** (Article X → many) = Complex article with many prerequisites
4. **Connected components** = Related legal topics

---

## Most Referenced Articles (Graph Hubs)

### Civil Code Top Nodes

```
Article 131  — cited by ~47 articles
  └─ defects of consent, fraud, duress → most fundamental

Article 42   — cited by ~32 articles
  └─ legal capacity → prerequisite for many contract rules

Article 123  — cited by ~18 articles
  └─ essential mistakes → validity ground
```

**Interpretation:** These are **core legal concepts** — articles that explore them tend to cite these foundational rules.

### Why This Matters for Retrieval

When the graph finds these hub articles during expansion, it pulls in a wealth of related articles. Example:

```
Query: "عقد باطل" (void contract)
  ↓
Vector finds: Article 123 (0.89 score)
  ↓
Graph expands: Article 123 → Article 131 (duress) → [14 more articles]
  ↓
Result: User sees why contract is void (defects, not just essential mistake)
```

---

## Relationship Extraction Examples

### Example 1: Article 14 (From Civil Code)

**Text (Arabic):**
```
في الأحوال المنصوص عليها في المادتين السابقتين 
إذا كان أحد الزوجين مصرياً وقت انعقاد الزواج 
يسري القانون المصري وحده
```

**Translation:**
> "In the cases provided for in the two preceding articles, if one of the two spouses is an Egyptian at the time of the conclusion of the marriage, Egyptian law alone shall apply..."

**Extracted References:**
- Detects: `المادتين السابقتين` + context check
- Extracts: Article 14 → Articles 12 and 13
- Edge: `{"source": "14", "target": "12"}` and `{"source": "14", "target": "13"}`

### Example 2: Article 123 (Essential Mistakes)

**Text (Arabic):**
```
لا يؤثر في صحة العقد مجرد الغلط في الحساب
```

**Translation:**
> "Mere mistakes of calculation or clerical mistakes do not affect the validity of a contract..."

**Extracted References:**
- Detects: `الغلط` (mistake) relates to Article 120-122 (adjacent topic)
- Also checks English text for explicit citations
- Edges: `{"source": "123", "target": "120"}`, `{"source": "123", "target": "121"}`

### Example 3: Commercial Code (Article 232)

**Graph Structure:**
```
Edge chain:
  126 → 232      (foundational company law)
  232 → 240      (subsidiaries/branches)
  232 → 251      (specific form requirements)
  252 → 257      (amendments)
  257 → 254      (cross-reference back to types)
```

**Interpretation:** Article 232 is a junction point — forms depend on company type (254), lead to variations (240, 251), and amendments cycle back (257→254).

---

## Graph Statistics by Domain

### Civil Code Graph

| Metric | Value | Meaning |
|---|---|---|
| Nodes | 1,105 | Total articles in corpus |
| Edges | ~2,547 | Cross-reference connections |
| Avg out-degree | 2.3 | Average article cites ~2-3 others |
| Max in-degree | 47 | Article 131 most cited |
| Density | 0.002 | Sparse graph (expected for legal text) |

### Labour Law Graph

| Metric | Value | Notes |
|---|---|---|
| Nodes | ~300 | Smaller, more modular |
| Edges | ~1,200 | Fewer interconnections |
| Avg out-degree | 4.0 | Articles cite more local peers |
| Clustering | high | Grouped by employment topics |

### Commercial Law Graph

| Metric | Value | Notes |
|---|---|---|
| Nodes | ~250 | Specialized, trade-focused |
| Edges | ~900 | Medium connectivity |
| Hub centrality | Article 232 | Company/partnership hub |

---

## Known Issues in Graph Extraction

⚠️ **OCR Artifacts in Nodes**

Some node names are corrupted (remnants of OCR errors):
- `"None"` — parsed null article number
- `"Article1022"` — missing space in English text
- `"1104 (3)"` — malformed article with section notation
- `"مادة 764"` vs `"764"` — inconsistent normalization (mixed Arabic/numeric formats)

**Impact:** Doesn't break graph structure (edges still valid), but clutters the node list and can cause missed expansions if a query discovers these malformed nodes.

**Fix:** Clean during corpus ingest (normalize all numbers to pure ASCII digits).

---

## Using Relationships in Queries

### Example: Contract Audit Query

**Scenario:** User uploads a contract and asks: "Are there capacity issues?"

```
Agent Query: "عدم القدرة على التعاقد" (Lack of capacity)
              
Vector Search:
  ├─ Article 42 (capacity definition) — 0.94
  ├─ Article 45 (lack of discretion) — 0.88
  └─ Article 44 (age of majority) — 0.81

Graph Expansion (from Article 42):
  Article 42 → [Article 44, Article 45, Article 131]
  Article 44 → [Article 46]
  Article 45 → [Article 47]

Final Result: 9 articles returned
  ├─ Article 42 (core: capacity)
  ├─ Article 44 (majority age)
  ├─ Article 45 (minors/incapacity)
  ├─ Article 46 (limited capacity)
  ├─ Article 47 (guardianship rules)
  ├─ Article 131 (vices of consent → related)
  ├─ [...3 more expanded articles]

Agent can now:
  1. Check if any contracting party is a minor → Article 44
  2. If yes, confirm lack of discretion → Article 45
  3. Verify guardianship coverage → Article 47
  4. Check for consent defects → Article 131
```

---

## Summary

**Graph Relationships = Directional Legal Citation Edges**

- **Extracted from:** Explicit article-to-article references in legal text
- **Pattern:** `Article A → Article B` (A cites B)
- **Context:** Legal keywords + proximity validation
- **Purpose:** Enable multi-hop retrieval (find related articles the vector search missed)
- **Benefit:** Comprehensive, grounded legal knowledge base for auditors & agents
- **Domains:** Separate graphs per law (Civil, Labour, Commercial)
- **Hub articles:** Most-cited foundational concepts (42, 131 in Civil)
- **Known issue:** OCR artifacts in some node names (doesn't break functionality)
