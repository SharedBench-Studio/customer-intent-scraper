# DB Extraction: Move Database Layer out of `app.py`

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract all SQLite data-loading logic from `app.py` into a new standalone `db.py` module that has zero Streamlit dependencies. Thin cached wrapper functions remain in `app.py`. Tests will import from `db.py` directly, eliminating the Streamlit import penalty on test runs.

**Architecture:**

```
db.py                      app.py
─────────────────          ──────────────────────────────────────────────
get_db(path)               @st.cache_data load_reply_stats(ttl_hash)
  context manager            └─ calls db.query_reply_stats(db_path)

query_replies(db_path,     @st.cache_data load_queries_df(ttl_hash)
  discussion_id)             └─ calls db.query_queries_df(db_path)

query_reply_stats(db_path) @st.cache_data load_retrievability_df(ttl_hash)
                             └─ calls db.query_retrievability_df(db_path)
query_queries_df(db_path)
                           load_replies(discussion_id)
query_retrievability_df      └─ calls db.query_replies(db_path, id)
  (db_path)
```

**Naming convention:** Pure DB functions in `db.py` are named `query_*` (accept explicit `db_path`, return `pd.DataFrame`, raise on error). Streamlit wrappers in `app.py` keep existing `load_*` names (supply `db_path`, catch exceptions, call `st.error`).

**Tech Stack:** Python 3.12, sqlite3 (`contextlib.contextmanager`), pandas, Streamlit (only in `app.py`)

**Resolves:** A2 (app.py size/responsibility), D3 (DB connection boilerplate), R3 (connection leaks)

---

## Task 1: Create `db.py` with `get_db` and `query_replies`, update test import

**Files:**
- Create: `db.py`
- Modify: `tests/test_reply_loading.py` (change import from `app` to `db`)

### Step 1: Update test import (make it fail first)

Edit `tests/test_reply_loading.py` line 8:

```python
# BEFORE:
from app import _query_replies

# AFTER:
from db import query_replies
```

Also rename the three call sites from `_query_replies(temp_db, ...)` to `query_replies(temp_db, ...)`.

### Step 2: Run test to verify it fails

```bash
cd C:/Github/scraping-copilot
python -m pytest tests/test_reply_loading.py -v
```

Expected: `ModuleNotFoundError: No module named 'db'`

### Step 3: Create `db.py`

Create `C:/Github/scraping-copilot/db.py`:

```python
"""
db.py — Pure SQLite data-access layer for the scraping-copilot dashboard.

Rules:
- No Streamlit imports anywhere in this file.
- All public functions accept an explicit db_path argument.
- All public functions return pd.DataFrame (empty on empty result,
  raise exceptions on DB errors — callers decide how to handle).
- get_db() is a context manager that guarantees connection cleanup.
"""

import sqlite3
import pandas as pd
from contextlib import contextmanager


@contextmanager
def get_db(path: str):
    """
    Context manager that opens a SQLite connection and guarantees close.

    Usage:
        with get_db(db_path) as conn:
            df = pd.read_sql_query(sql, conn)
    """
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def query_replies(db_path: str, discussion_id: str) -> pd.DataFrame:
    """Return all replies for a single discussion, ordered by publish_date."""
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM replies WHERE parent_id = ? ORDER BY publish_date",
            conn,
            params=(discussion_id,),
        )


def query_reply_stats(db_path: str) -> pd.DataFrame:
    """Return per-discussion reply counts and concatenated reply text.

    Columns: parent_id, agg_reply_count, all_reply_text
    """
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT parent_id,
                   COUNT(*) as agg_reply_count,
                   GROUP_CONCAT(content, ' ') as all_reply_text
            FROM replies
            GROUP BY parent_id
            """,
            conn,
        )


def query_queries_df(db_path: str) -> pd.DataFrame:
    """Return extracted queries joined with their source discussion metadata.

    Columns: id, query_text, method, product_area, created_at,
             source_title, source_url
    """
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT q.id, q.query_text, q.method, q.product_area,
                   q.created_at, d.title as source_title, d.url as source_url
            FROM queries q
            LEFT JOIN discussions d ON d.id = q.source_id
            """,
            conn,
        )


def query_retrievability_df(db_path: str) -> pd.DataFrame:
    """Return retrievability results joined with query text.

    Columns: query_id, doc_path, doc_title, rank, score,
             query_text, product_area
    """
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT r.query_id, r.doc_path, r.doc_title, r.rank, r.score,
                   q.query_text, q.product_area
            FROM retrievability_results r
            JOIN queries q ON q.id = r.query_id
            """,
            conn,
        )
```

### Step 4: Run test to verify it passes

```bash
python -m pytest tests/test_reply_loading.py -v
```

Expected: 5 passed. No `UserWarning` about `app.py:238` (Streamlit no longer imported).

### Step 5: Verify clean import

```bash
python -c "import db; print('OK — no Streamlit errors')"
```

Expected: `OK — no Streamlit errors` in under 0.2s.

### Step 6: Commit

```bash
git add db.py tests/test_reply_loading.py
git commit -m "feat: extract db.py with get_db context manager and query functions

Resolves A2 (app.py size) and D3 (DB connection boilerplate).
Tests now import from db.py directly — no Streamlit import on test runs."
```

---

## Task 2: Wire `app.py` thin wrappers to use `db.query_*`

**Files:**
- Modify: `app.py` — add `import db`, replace 5 function bodies

### Step 1: Add `import db` to `app.py`

After the existing imports block (around line 10), add:

```python
import db
```

### Step 2: Replace the five DB function bodies

Find the five functions currently at lines ~260–349. Replace all five with:

```python
def _query_replies(db_path, discussion_id):
    """Thin shim — delegates to db.query_replies."""
    return db.query_replies(db_path, discussion_id)


def load_replies(discussion_id):
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        return db.query_replies(db_path, discussion_id)
    except Exception as e:
        st.error(f"Error loading replies: {e}")
        return pd.DataFrame()


@st.cache_data
def load_reply_stats(ttl_hash=None):
    """Load per-discussion reply counts and aggregated reply text for Topic Explorer."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        return db.query_reply_stats(db_path)
    except Exception as e:
        st.error(f"Error loading reply stats: {e}")
        return pd.DataFrame()


@st.cache_data
def load_queries_df(ttl_hash=None):
    """Load extracted queries with their source discussion title."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        return db.query_queries_df(db_path)
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
        return db.query_retrievability_df(db_path)
    except Exception as e:
        st.error(f"Error loading retrievability results: {e}")
        return pd.DataFrame()
```

### Step 3: Run full test suite

```bash
python -m pytest tests/ -v
```

Expected: all tests pass.

### Step 4: Smoke-test the Streamlit app

```bash
streamlit run app.py
```

Verify: General Dashboard loads, Topic Explorer Reply Intelligence section works, Query Bank tab loads.

### Step 5: Clean up `_query_replies` shim if unused

```bash
grep -n "_query_replies" app.py
```

If zero results, delete the shim — it was only needed when the test imported it directly.

### Step 6: Commit

```bash
git add app.py
git commit -m "refactor: wire app.py load_* wrappers to delegate to db.py

Eliminates repeated connect/try/finally/close boilerplate in app.py."
```

---

## Task 3: Add tests for all `db.py` query functions

**Files:**
- Create: `tests/test_db.py`

### Step 1: Create the test file

Create `C:/Github/scraping-copilot/tests/test_db.py`:

```python
"""
Unit tests for db.py pure query functions.
No Streamlit is imported anywhere in this file.
"""

import sqlite3
import pytest
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import db


@pytest.fixture
def temp_db(tmp_path):
    path = str(tmp_path / "test.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE discussions (id TEXT PRIMARY KEY, title TEXT, url TEXT)")
    conn.execute("""CREATE TABLE replies (
        id TEXT PRIMARY KEY, parent_id TEXT, author TEXT,
        publish_date TEXT, content TEXT, thumbs_up_count INTEGER
    )""")
    conn.execute("""CREATE TABLE queries (
        id TEXT PRIMARY KEY, query_text TEXT, method TEXT,
        product_area TEXT, created_at TEXT, source_id TEXT
    )""")
    conn.execute("""CREATE TABLE retrievability_results (
        query_id TEXT, doc_path TEXT, doc_title TEXT, rank INTEGER, score REAL
    )""")
    conn.execute("INSERT INTO discussions VALUES ('d1', 'Post One', 'http://example.com/d1')")
    conn.execute("INSERT INTO discussions VALUES ('d2', 'Post Two', 'http://example.com/d2')")
    conn.execute("INSERT INTO replies VALUES ('r1', 'd1', 'alice', '2026-01-01', 'Great post', 3)")
    conn.execute("INSERT INTO replies VALUES ('r2', 'd1', 'bob',   '2026-01-02', 'I agree',   1)")
    conn.execute("INSERT INTO replies VALUES ('r3', 'd2', 'carol', '2026-01-01', 'Helpful',   5)")
    conn.execute("INSERT INTO queries VALUES ('q1', 'How do I enable Copilot?', 'title_question', 'Teams', '2026-01-01', 'd1')")
    conn.execute("INSERT INTO queries VALUES ('q2', 'Can I disable it?', 'content_question', NULL, '2026-01-02', 'd1')")
    conn.execute("INSERT INTO retrievability_results VALUES ('q1', '/docs/setup.md', 'Setup Guide', 1, 0.82)")
    conn.execute("INSERT INTO retrievability_results VALUES ('q1', '/docs/admin.md', 'Admin Guide', 2, 0.45)")
    conn.commit()
    conn.close()
    return path


# get_db

def test_get_db_yields_connection(temp_db):
    with db.get_db(temp_db) as conn:
        result = conn.execute("SELECT COUNT(*) FROM discussions").fetchone()
        assert result[0] == 2


def test_get_db_closes_connection_after_block(temp_db):
    with db.get_db(temp_db) as conn:
        captured = conn
    with pytest.raises(Exception):
        captured.execute("SELECT 1")


# query_replies

def test_query_replies_filters_by_discussion(temp_db):
    df = db.query_replies(temp_db, 'd1')
    assert len(df) == 2
    assert set(df['author'].tolist()) == {'alice', 'bob'}


def test_query_replies_ordered_by_date(temp_db):
    df = db.query_replies(temp_db, 'd1')
    assert df.iloc[0]['author'] == 'alice'


def test_query_replies_empty_for_unknown_id(temp_db):
    df = db.query_replies(temp_db, 'nonexistent')
    assert len(df) == 0


# query_reply_stats

def test_query_reply_stats_one_row_per_discussion(temp_db):
    df = db.query_reply_stats(temp_db)
    assert set(df['parent_id'].tolist()) == {'d1', 'd2'}


def test_query_reply_stats_counts_correctly(temp_db):
    df = db.query_reply_stats(temp_db)
    d1 = df[df['parent_id'] == 'd1'].iloc[0]
    assert d1['agg_reply_count'] == 2


def test_query_reply_stats_concatenates_text(temp_db):
    df = db.query_reply_stats(temp_db)
    d1 = df[df['parent_id'] == 'd1'].iloc[0]
    assert 'Great post' in d1['all_reply_text']


# query_queries_df

def test_query_queries_df_returns_all_queries(temp_db):
    df = db.query_queries_df(temp_db)
    assert len(df) == 2


def test_query_queries_df_joins_source_title(temp_db):
    df = db.query_queries_df(temp_db)
    q1 = df[df['id'] == 'q1'].iloc[0]
    assert q1['source_title'] == 'Post One'


def test_query_queries_df_columns_present(temp_db):
    df = db.query_queries_df(temp_db)
    for col in ['id', 'query_text', 'method', 'product_area', 'created_at', 'source_title', 'source_url']:
        assert col in df.columns


# query_retrievability_df

def test_query_retrievability_df_returns_results(temp_db):
    df = db.query_retrievability_df(temp_db)
    assert len(df) == 2


def test_query_retrievability_df_joins_query_text(temp_db):
    df = db.query_retrievability_df(temp_db)
    assert 'How do I enable Copilot?' in df['query_text'].tolist()


def test_query_retrievability_df_columns_present(temp_db):
    df = db.query_retrievability_df(temp_db)
    for col in ['query_id', 'doc_path', 'doc_title', 'rank', 'score', 'query_text', 'product_area']:
        assert col in df.columns


# Import isolation

def test_db_module_does_not_import_streamlit():
    import sys
    import inspect
    for mod in list(sys.modules):
        if mod == 'db':
            del sys.modules[mod]
    streamlit_before = 'streamlit' in sys.modules
    import db as fresh_db  # noqa: F401
    streamlit_after = 'streamlit' in sys.modules
    assert streamlit_before or not streamlit_after, \
        "Importing db.py caused streamlit to load. db.py must be Streamlit-free."
    source = inspect.getsource(fresh_db)
    assert 'import streamlit' not in source
    assert 'from streamlit' not in source
```

### Step 2: Run the tests

```bash
python -m pytest tests/test_db.py -v
```

Expected: All tests pass in under 1 second.

### Step 3: Run full suite

```bash
python -m pytest tests/ -v
```

### Step 4: Commit

```bash
git add tests/test_db.py
git commit -m "test: comprehensive unit tests for db.py including import-isolation guard"
```

---

## Summary of changes

| File | Action | What changes |
|---|---|---|
| `db.py` | Create | `get_db` context manager + 4 `query_*` functions, no Streamlit |
| `app.py` | Modify | Add `import db`; replace 5 function bodies with thin wrappers |
| `tests/test_reply_loading.py` | Modify | Import from `db` instead of `app`; update 3 call sites |
| `tests/test_db.py` | Create | 15 unit tests + import-isolation guard |

## Pitfalls

1. **`_query_replies` shim:** After Task 2, check `grep -n "_query_replies" app.py`. If zero callers, delete it.
2. **`load_data` in `app.py` is NOT extracted** — it has Streamlit post-processing and is called at module level. Leave it in `app.py`.
3. **`queries` and `retrievability_results` tables may not exist** — the `try/except` wrappers in `app.py` handle `OperationalError: no such table`. No change from current behavior.
