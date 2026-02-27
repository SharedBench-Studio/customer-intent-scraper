# Query Bank & AI Retrievability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract real customer queries from scraped discussions using rule-based NLP, then score those queries against a local Markdown docs folder using TF-IDF cosine similarity, with a new Query Bank dashboard tab showing results and coverage gaps.

**Architecture:** Three new components — `extract_queries.py` (rule-based query extraction → `queries` SQLite table), `test_retrievability.py` (TF-IDF doc indexer → `retrievability_results` table), and a new Query Bank tab in `app.py`. Each component is standalone and runnable from the Streamlit sidebar or CLI. Option B (LLM reformulation) is documented separately in `docs/plans/query-extraction-llm-upgrade.md` for future implementation.

**Tech Stack:** Python stdlib `re`, `sqlite3`, scikit-learn TF-IDF + cosine_similarity, Streamlit, pandas. No new dependencies needed.

---

## Database Schema (new tables)

```sql
CREATE TABLE queries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text   TEXT NOT NULL,
    source_id    TEXT,        -- FK to discussions.id
    method       TEXT,        -- 'title_question' | 'content_question' | 'title_implicit'
    product_area TEXT,        -- copied from analysis_product_area if available
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE retrievability_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id   INTEGER,       -- FK to queries.id
    doc_path   TEXT,          -- relative path to .md file
    doc_title  TEXT,          -- first H1 heading from file
    rank       INTEGER,       -- 1-5
    score      REAL,          -- cosine similarity 0.0-1.0
    tested_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### Task 1: Rule-based query extraction (`extract_queries.py`)

**Files:**
- Create: `extract_queries.py`
- Create: `tests/test_extract_queries.py`

**Step 1: Write failing tests**

Create `tests/test_extract_queries.py`:

```python
import pytest
from extract_queries import extract_queries_from_discussion, deduplicate_queries


def test_extracts_title_question():
    discussion = {"id": "d1", "title": "How do I enable Copilot for my tenant?",
                  "content": "", "analysis_product_area": None}
    queries = extract_queries_from_discussion(discussion)
    texts = [q["query_text"] for q in queries]
    assert "How do I enable Copilot for my tenant?" in texts
    assert any(q["method"] == "title_question" for q in queries)


def test_extracts_content_questions():
    discussion = {"id": "d2", "title": "Copilot issue",
                  "content": "I have a problem. Is there a way to reset Copilot? Also, can I disable it?",
                  "analysis_product_area": None}
    queries = extract_queries_from_discussion(discussion)
    texts = [q["query_text"] for q in queries]
    assert "Is there a way to reset Copilot?" in texts
    assert "can I disable it?" in texts
    assert all(q["method"] == "content_question" for q in queries
               if q["query_text"] in ["Is there a way to reset Copilot?", "can I disable it?"])


def test_extracts_implicit_title():
    discussion = {"id": "d3", "title": "Copilot not showing in Teams",
                  "content": "It just stopped working.", "analysis_product_area": "Teams"}
    queries = extract_queries_from_discussion(discussion)
    texts = [q["query_text"] for q in queries]
    assert "Copilot not showing in Teams" in texts
    assert any(q["method"] == "title_implicit" for q in queries)


def test_no_duplicate_title_and_content_question():
    # Title is a question AND appears in content — should not produce duplicate
    discussion = {"id": "d4", "title": "How do I enable Copilot?",
                  "content": "How do I enable Copilot? I have tried everything.",
                  "analysis_product_area": None}
    queries = extract_queries_from_discussion(discussion)
    texts = [q["query_text"] for q in queries]
    assert texts.count("How do I enable Copilot?") == 1


def test_skips_very_short_titles():
    discussion = {"id": "d5", "title": "Help", "content": "", "analysis_product_area": None}
    queries = extract_queries_from_discussion(discussion)
    assert len(queries) == 0


def test_deduplicate_queries_removes_near_identical():
    queries = [
        {"query_text": "How do I enable Copilot?", "source_id": "d1", "method": "title_question", "product_area": None},
        {"query_text": "How do I enable Copilot?", "source_id": "d2", "method": "content_question", "product_area": None},
        {"query_text": "How do I disable Copilot?", "source_id": "d3", "method": "title_question", "product_area": None},
    ]
    deduped = deduplicate_queries(queries)
    texts = [q["query_text"] for q in deduped]
    assert texts.count("How do I enable Copilot?") == 1
    assert "How do I disable Copilot?" in texts
```

**Step 2: Run tests to verify they fail**

```bash
cd C:\Github\scraping-copilot
python -m pytest tests/test_extract_queries.py -v
```

Expected: `ImportError: cannot import name 'extract_queries_from_discussion'`

**Step 3: Implement `extract_queries.py`**

Create `extract_queries.py` with this exact content:

```python
"""
Rule-based query extraction from scraped discussions.
Extracts real customer questions to use as AI retrievability test queries.

Usage:
    python extract_queries.py --db discussions.db

Future (LLM upgrade): see docs/plans/query-extraction-llm-upgrade.md
"""

import argparse
import re
import sqlite3


MIN_TITLE_LENGTH = 10       # skip titles shorter than this
MAX_TITLE_LENGTH = 200      # skip titles longer than this (likely noise)
MAX_CONTENT_QUESTIONS = 3   # max questions extracted per discussion content


def extract_queries_from_discussion(discussion):
    """
    Extract query candidates from a single discussion dict.
    Returns list of dicts: {query_text, source_id, method, product_area}
    """
    queries = []
    seen_texts = set()
    title = (discussion.get("title") or "").strip()
    content = (discussion.get("content") or "").strip()
    source_id = discussion.get("id")
    product_area = discussion.get("analysis_product_area")

    def add(text, method):
        text = text.strip()
        if text and text not in seen_texts:
            seen_texts.add(text)
            queries.append({
                "query_text": text,
                "source_id": source_id,
                "method": method,
                "product_area": product_area,
            })

    # Rule 1: Title is a question
    if title.endswith("?") and MIN_TITLE_LENGTH <= len(title) <= MAX_TITLE_LENGTH:
        add(title, "title_question")

    # Rule 2: Sentences in content that end with ?
    if content:
        sentences = re.split(r'(?<=[.!?])\s+', content)
        count = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence.endswith("?") and MIN_TITLE_LENGTH <= len(sentence) <= MAX_TITLE_LENGTH:
                add(sentence, "content_question")
                count += 1
                if count >= MAX_CONTENT_QUESTIONS:
                    break

    # Rule 3: Short non-question title treated as implicit query
    if (not title.endswith("?")
            and MIN_TITLE_LENGTH <= len(title) <= MAX_TITLE_LENGTH
            and not queries):  # only if no questions found yet
        add(title, "title_implicit")

    return queries


def deduplicate_queries(queries):
    """Remove exact duplicate query_text values, keeping first occurrence."""
    seen = set()
    result = []
    for q in queries:
        if q["query_text"] not in seen:
            seen.add(q["query_text"])
            result.append(q)
    return result


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            query_text   TEXT NOT NULL,
            source_id    TEXT,
            method       TEXT,
            product_area TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def load_discussions(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, title, content, analysis_product_area FROM discussions")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_queries(conn, queries):
    conn.executemany("""
        INSERT INTO queries (query_text, source_id, method, product_area)
        VALUES (:query_text, :source_id, :method, :product_area)
    """, queries)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="discussions.db")
    args = parser.parse_args()

    print(f"Loading discussions from {args.db}...")
    discussions = load_discussions(args.db)
    print(f"  {len(discussions)} discussions loaded.")

    all_queries = []
    for d in discussions:
        all_queries.extend(extract_queries_from_discussion(d))

    all_queries = deduplicate_queries(all_queries)
    print(f"  {len(all_queries)} unique queries extracted.")

    conn = sqlite3.connect(args.db)
    ensure_table(conn)
    # Clear previous extraction before re-running
    conn.execute("DELETE FROM queries")
    save_queries(conn, all_queries)
    conn.close()
    print("Done. Queries saved to 'queries' table.")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_extract_queries.py -v
```

Expected: 6 tests PASS.

**Step 5: Smoke-test against the real DB**

```bash
python extract_queries.py --db discussions.db
```

Expected output like:
```
Loading discussions from discussions.db...
  3309 discussions loaded.
  NNNN unique queries extracted.
Done. Queries saved to 'queries' table.
```

Then verify in SQLite:
```bash
python -c "
import sqlite3
conn = sqlite3.connect('discussions.db')
cur = conn.cursor()
cur.execute('SELECT method, COUNT(*) FROM queries GROUP BY method')
for row in cur.fetchall(): print(row)
cur.execute('SELECT query_text FROM queries LIMIT 5')
for row in cur.fetchall(): print(row)
conn.close()
"
```

**Step 6: Commit**

```bash
git add extract_queries.py tests/test_extract_queries.py
git commit -m "feat: rule-based query extraction from community discussions"
```

---

### Task 2: Local doc TF-IDF retrievability scorer (`test_retrievability.py`)

**Files:**
- Create: `test_retrievability.py`
- Create: `tests/test_retrievability_scorer.py`

**Step 1: Write failing tests**

Create `tests/test_retrievability_scorer.py`:

```python
import os
import pytest
from test_retrievability import index_docs, score_query, extract_title_from_markdown


@pytest.fixture
def doc_dir(tmp_path):
    # Create minimal markdown docs
    (tmp_path / "copilot-setup.md").write_text(
        "# Setting Up Microsoft 365 Copilot\nLearn how to configure Copilot for your tenant.\n"
        "You need admin permissions to enable Copilot.", encoding="utf-8"
    )
    (tmp_path / "teams-integration.md").write_text(
        "# Copilot in Teams\nCopilot integrates with Microsoft Teams to summarize meetings.\n"
        "Enable it from the Teams admin center.", encoding="utf-8"
    )
    (tmp_path / "excel-features.md").write_text(
        "# Excel Copilot Features\nCopilot in Excel can analyze data and generate formulas.",
        encoding="utf-8"
    )
    return str(tmp_path)


def test_index_docs_finds_markdown_files(doc_dir):
    docs = index_docs(doc_dir)
    assert len(docs) == 3
    assert all("path" in d and "title" in d and "text" in d for d in docs)


def test_extract_title_from_markdown():
    text = "# Setting Up Microsoft 365 Copilot\nSome content here."
    assert extract_title_from_markdown(text) == "Setting Up Microsoft 365 Copilot"


def test_extract_title_falls_back_to_filename():
    text = "No heading here, just content."
    assert extract_title_from_markdown(text, fallback="my-doc") == "my-doc"


def test_score_query_returns_top_n(doc_dir):
    docs = index_docs(doc_dir)
    results = score_query("How do I enable Copilot for my tenant?", docs, top_n=2)
    assert len(results) == 2
    assert all("rank" in r and "score" in r and "doc_path" in r for r in results)
    assert results[0]["rank"] == 1
    assert results[1]["rank"] == 2


def test_score_query_ranks_relevant_doc_higher(doc_dir):
    docs = index_docs(doc_dir)
    results = score_query("How do I configure Copilot for my tenant admin?", docs, top_n=3)
    top_doc = results[0]["doc_path"]
    assert "copilot-setup" in top_doc


def test_score_query_returns_empty_for_no_docs():
    results = score_query("anything", [], top_n=5)
    assert results == []
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_retrievability_scorer.py -v
```

Expected: `ImportError: cannot import name 'index_docs'`

**Step 3: Implement `test_retrievability.py`**

```python
"""
Local Markdown doc TF-IDF retrievability scorer.
Indexes a folder of .md files and scores queries from the queries table.

Usage:
    python test_retrievability.py --docs-path C:/path/to/docs --db discussions.db --top-n 5
"""

import argparse
import os
import re
import sqlite3

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def extract_title_from_markdown(text, fallback="untitled"):
    """Return the first H1 heading, or fallback if none found."""
    match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def index_docs(docs_path):
    """
    Walk docs_path recursively for .md files.
    Returns list of dicts: {path, title, text}
    """
    docs = []
    for root, _, files in os.walk(docs_path):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            full_path = os.path.join(root, fname)
            try:
                with open(full_path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                continue
            fallback = os.path.splitext(fname)[0]
            docs.append({
                "path": os.path.relpath(full_path, docs_path),
                "title": extract_title_from_markdown(text, fallback=fallback),
                "text": text,
            })
    return docs


def score_query(query_text, docs, top_n=5):
    """
    Score a single query against indexed docs using TF-IDF cosine similarity.
    Returns list of top_n results: {rank, doc_path, doc_title, score}
    """
    if not docs:
        return []

    corpus = [d["text"] for d in docs]
    vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
    try:
        doc_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query_text])
    except ValueError:
        return []

    scores = cosine_similarity(query_vec, doc_matrix).flatten()
    top_indices = np.argsort(scores)[::-1][:top_n]

    results = []
    for rank, idx in enumerate(top_indices, start=1):
        results.append({
            "rank": rank,
            "doc_path": docs[idx]["path"],
            "doc_title": docs[idx]["title"],
            "score": float(scores[idx]),
        })
    return results


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retrievability_results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id  INTEGER,
            doc_path  TEXT,
            doc_title TEXT,
            rank      INTEGER,
            score     REAL,
            tested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def load_queries(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, query_text FROM queries")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_results(conn, results):
    conn.executemany("""
        INSERT INTO retrievability_results (query_id, doc_path, doc_title, rank, score)
        VALUES (:query_id, :doc_path, :doc_title, :rank, :score)
    """, results)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-path", required=True, help="Path to folder of .md files")
    parser.add_argument("--db", default="discussions.db")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()

    print(f"Indexing docs from {args.docs_path}...")
    docs = index_docs(args.docs_path)
    if not docs:
        print("No .md files found. Check --docs-path.")
        return
    print(f"  {len(docs)} documents indexed.")

    print(f"Loading queries from {args.db}...")
    queries = load_queries(args.db)
    if not queries:
        print("No queries found. Run extract_queries.py first.")
        return
    print(f"  {len(queries)} queries loaded.")

    conn = sqlite3.connect(args.db)
    ensure_table(conn)
    # Clear previous results before re-running
    conn.execute("DELETE FROM retrievability_results")
    conn.commit()

    total = 0
    for i, q in enumerate(queries):
        results = score_query(q["query_text"], docs, top_n=args.top_n)
        rows = [{**r, "query_id": q["id"]} for r in results]
        save_results(conn, rows)
        total += len(rows)
        if (i + 1) % 100 == 0:
            print(f"  Scored {i + 1}/{len(queries)} queries...")

    conn.close()
    print(f"Done. {total} results saved to 'retrievability_results' table.")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_retrievability_scorer.py -v
```

Expected: 6 tests PASS.

**Step 5: Commit**

```bash
git add test_retrievability.py tests/test_retrievability_scorer.py
git commit -m "feat: TF-IDF doc indexer and retrievability scorer"
```

---

### Task 3: Query Bank tab in `app.py`

**Files:**
- Modify: `app.py:270` (tabs definition)
- Modify: `app.py:104-135` (sidebar — add Query Bank controls)
- Modify: `app.py:602` (end of file — add tab3 content)

**Step 1: Add helper functions before the tabs**

Add two cached data-loading helpers after `load_reply_stats` (around line 262, before the `db_path = "discussions.db"` variable):

```python
@st.cache_data
def load_queries_df(ttl_hash=None):
    """Load extracted queries with their source discussion title."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("""
            SELECT q.id, q.query_text, q.method, q.product_area,
                   q.created_at, d.title as source_title, d.url as source_url
            FROM queries q
            LEFT JOIN discussions d ON d.id = q.source_id
        """, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error loading queries: {e}")
        return pd.DataFrame()


@st.cache_data
def load_retrievability_df(ttl_hash=None):
    """Load retrievability results joined with query text."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("""
            SELECT r.query_id, r.doc_path, r.doc_title, r.rank, r.score,
                   q.query_text, q.product_area
            FROM retrievability_results r
            JOIN queries q ON q.id = r.query_id
        """, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error loading retrievability results: {e}")
        return pd.DataFrame()
```

**Step 2: Add sidebar controls for Query Bank**

In `app.py`, find the `with st.sidebar.expander("Run Analysis"):` block. Add a new expander AFTER it (before the "Refresh Data" button):

```python
with st.sidebar.expander("Query Bank"):
    st.write("Extract customer queries and test doc retrievability.")

    if st.button("Extract Queries"):
        st.info("Extracting queries from discussions...")
        result = subprocess.run(
            [sys.executable, "extract_queries.py", "--db", "discussions.db"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            st.success("Queries extracted!")
            st.code(result.stdout)
            st.cache_data.clear()
        else:
            st.error("Extraction failed.")
            st.code(result.stderr)

    st.markdown("---")
    docs_path = st.text_input("Docs folder path", placeholder="C:/path/to/your/docs")
    top_n = st.number_input("Top N results per query", min_value=1, max_value=10, value=5)

    if st.button("Run Retrievability Test"):
        if not docs_path:
            st.warning("Enter a docs folder path first.")
        else:
            st.info("Scoring queries against docs...")
            result = subprocess.run(
                [sys.executable, "test_retrievability.py",
                 "--docs-path", docs_path,
                 "--db", "discussions.db",
                 "--top-n", str(top_n)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                st.success("Retrievability test complete!")
                st.code(result.stdout)
                st.cache_data.clear()
            else:
                st.error("Test failed.")
                st.code(result.stderr)
```

**Step 3: Add tab3 to the tabs definition**

Find line 270:
```python
tab1, tab2 = st.tabs(["General Dashboard", "Topic Explorer"])
```

Replace with:
```python
tab1, tab2, tab3 = st.tabs(["General Dashboard", "Topic Explorer", "Query Bank"])
```

**Step 4: Add tab3 content at the end of `app.py`**

After the closing of the `with tab2:` block (end of file, after line 602), add:

```python
    with tab3:
        st.header("Query Bank")
        st.write("Real customer queries extracted from community discussions, scored against your documentation.")

        queries_df = load_queries_df(ttl_hash=last_updated)
        retrievability_df = load_retrievability_df(ttl_hash=last_updated)

        if queries_df.empty:
            st.info("No queries yet. Click **Extract Queries** in the sidebar to get started.")
        else:
            # --- Summary metrics ---
            total_q = len(queries_df)
            tested_q = retrievability_df["query_id"].nunique() if not retrievability_df.empty else 0
            avg_top1 = retrievability_df[retrievability_df["rank"] == 1]["score"].mean() if not retrievability_df.empty else None

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Queries", total_q)
            col2.metric("Queries Tested", tested_q)
            col3.metric("Avg Top-1 Score", f"{avg_top1:.3f}" if avg_top1 is not None else "—")

            # --- Method breakdown ---
            if "method" in queries_df.columns:
                method_counts = queries_df["method"].value_counts().reset_index()
                method_counts.columns = ["Method", "Count"]
                fig = px.bar(method_counts, x="Method", y="Count",
                             title="Queries by Extraction Method",
                             color="Method")
                st.plotly_chart(fig, use_container_width=True)

            # --- Query list ---
            st.subheader("Query List")
            search = st.text_input("Search queries", placeholder="filter by keyword...")
            filtered_q = queries_df
            if search:
                mask = queries_df["query_text"].str.contains(search, case=False, na=False)
                filtered_q = queries_df[mask]

            display_cols = ["query_text", "method", "product_area", "source_title"]
            display_cols = [c for c in display_cols if c in filtered_q.columns]
            q_selection = st.dataframe(
                filtered_q[display_cols].reset_index(drop=True),
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row"
            )

            # --- Query detail: top docs ---
            if q_selection.selection.rows and not retrievability_df.empty:
                selected_idx = q_selection.selection.rows[0]
                selected_q = filtered_q.iloc[selected_idx]
                query_id = selected_q["id"]

                st.subheader(f"Top docs for: *{selected_q['query_text']}*")
                if selected_q.get("source_title"):
                    st.caption(f"Source discussion: {selected_q['source_title']}")

                top_docs = retrievability_df[retrievability_df["query_id"] == query_id].sort_values("rank")
                if top_docs.empty:
                    st.info("This query hasn't been tested yet. Run the retrievability test.")
                else:
                    for _, row in top_docs.iterrows():
                        with st.container(border=True):
                            score_pct = f"{row['score']:.1%}"
                            st.markdown(f"**#{row['rank']}** — {row['doc_title']} `{score_pct}`")
                            st.caption(row["doc_path"])

            # --- Coverage gaps ---
            if not retrievability_df.empty:
                st.subheader("Coverage Gaps")
                st.write("Queries where the top-1 doc score is below 0.05 — likely missing or hard-to-find content.")
                top1 = retrievability_df[retrievability_df["rank"] == 1]
                gaps = top1[top1["score"] < 0.05][["query_text", "score", "product_area"]].copy()
                gaps["score"] = gaps["score"].round(4)
                if gaps.empty:
                    st.success("No significant coverage gaps found.")
                else:
                    st.dataframe(gaps.reset_index(drop=True), use_container_width=True)
```

**Step 5: Verify syntax**

```bash
cd C:\Github\scraping-copilot
python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('syntax OK')"
```

**Step 6: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All 11 tests PASS (5 existing + 6 new).

**Step 7: Commit**

```bash
git add app.py
git commit -m "feat: add Query Bank tab with sidebar controls and coverage gaps"
```

---

### Task 4: Document LLM upgrade path

**Files:**
- Create: `docs/plans/query-extraction-llm-upgrade.md`

**Step 1: Create the future-upgrade doc**

Create `docs/plans/query-extraction-llm-upgrade.md`:

```markdown
# Query Extraction: LLM Upgrade Plan (Option B)

> Status: DEFERRED — implement when Azure OpenAI credentials are available.
> Current implementation: see `extract_queries.py` (rule-based, Option A).

## Goal

Replace or augment rule-based extraction with GPT-4o reformulation for richer,
more accurate search queries — especially for implicit-intent posts that have no
explicit `?`.

## How to activate

### Step 1: Confirm credentials in `.env`

```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

Run `analyze_intent.py` on a few rows first to confirm credentials work.

### Step 2: Add `--use-llm` flag to `extract_queries.py`

Add to `main()` argument parser:
```python
parser.add_argument("--use-llm", action="store_true",
                    help="Use Azure OpenAI to reformulate implicit queries")
```

### Step 3: Add `reformulate_with_llm(discussion, client, deployment)` function

```python
def reformulate_with_llm(discussion, client, deployment):
    title = discussion.get("title", "")
    content = (discussion.get("content", "") or "")[:500]  # cap tokens
    prompt = f"""Given this customer discussion, write 1-3 search queries
this person would type into a help search to find documentation.
Return ONLY a JSON array of strings.

Title: {title}
Content: {content}"""

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        import json
        data = json.loads(response.choices[0].message.content)
        # Handle both {"queries": [...]} and bare [...]
        if isinstance(data, list):
            return data
        return data.get("queries", [])
    except Exception as e:
        print(f"LLM reformulation failed for {discussion.get('id')}: {e}")
        return []
```

### Step 4: Use LLM only for `title_implicit` results

In `main()`, after rule-based extraction, if `--use-llm`:

```python
if args.use_llm:
    from openai import AzureOpenAI
    from dotenv import load_dotenv
    load_dotenv()
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

    implicit = [d for d in discussions
                if all(q["method"] != "title_implicit"
                       or d["id"] != q["source_id"]
                       for q in all_queries)]
    print(f"  Reformulating {len(implicit)} implicit discussions via LLM...")
    for d in implicit:
        for text in reformulate_with_llm(d, client, deployment):
            all_queries.append({
                "query_text": text,
                "source_id": d["id"],
                "method": "llm_reformulation",
                "product_area": d.get("analysis_product_area"),
            })
```

### Step 5: Add `method = 'llm_reformulation'` to dashboard filter

In `app.py` Query Bank tab, the method breakdown chart already reads from the
`method` column — no changes needed. The new method will appear automatically.

## Estimated API cost

~1,000 discussions × ~300 tokens each = ~300K tokens
At gpt-4o pricing (~$5/1M input tokens) ≈ $1.50 for a full run.
```

**Step 2: Commit**

```bash
git add docs/plans/query-extraction-llm-upgrade.md
git commit -m "docs: add LLM query extraction upgrade plan for future implementation"
```

---

## Running the full pipeline

```bash
# Step 1: Extract queries
python extract_queries.py --db discussions.db

# Step 2: Score against your docs
python test_retrievability.py --docs-path C:/path/to/your/docs --db discussions.db --top-n 5

# Step 3: View in dashboard
streamlit run app.py
# → open Query Bank tab
```
