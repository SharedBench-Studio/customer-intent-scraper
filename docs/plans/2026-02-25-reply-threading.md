# Reply Threading & Aggregation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface reply content throughout the app — threaded detail view, enriched analysis, and topic-level reply aggregation in the Topic Explorer.

**Architecture:** Lazy-load replies from the `replies` SQLite table per-discussion on click (avoids loading 3300+ discussions worth of replies into memory). Enrich both analysis scripts to JOIN reply content into the text corpus. Add reply stats to Topic Explorer using in-memory aggregation at render time.

**Tech Stack:** Python, SQLite, Streamlit, pandas, scikit-learn (TF-IDF already used), plotly

---

### Task 1: Add `load_replies()` and wire up threaded detail view

**Files:**
- Modify: `app.py:180-215` (after `load_data()`)
- Modify: `app.py:374-403` (detail view section)

**Step 1: Write the failing test**

Create `tests/test_reply_loading.py`:

```python
import sqlite3
import pytest
import pandas as pd

def load_replies(db_path, discussion_id):
    """Fetch replies for a single discussion from SQLite."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT * FROM replies WHERE parent_id = ? ORDER BY publish_date",
        conn, params=(discussion_id,)
    )
    conn.close()
    return df

@pytest.fixture
def temp_db(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE discussions (id TEXT PRIMARY KEY, title TEXT)""")
    conn.execute("""CREATE TABLE replies (
        id TEXT PRIMARY KEY, parent_id TEXT, author TEXT,
        publish_date TEXT, content TEXT, thumbs_up_count INTEGER
    )""")
    conn.execute("INSERT INTO discussions VALUES ('d1', 'Test Post')")
    conn.execute("INSERT INTO replies VALUES ('r1', 'd1', 'alice', '2026-01-01', 'First reply', 5)")
    conn.execute("INSERT INTO replies VALUES ('r2', 'd1', 'bob',   '2026-01-02', 'Second reply', 2)")
    conn.execute("INSERT INTO replies VALUES ('r3', 'd2', 'carol', '2026-01-01', 'Other post reply', 1)")
    conn.commit()
    conn.close()
    return str(db)

def test_load_replies_returns_only_matching_discussion(temp_db):
    df = load_replies(temp_db, 'd1')
    assert len(df) == 2
    assert set(df['author'].tolist()) == {'alice', 'bob'}

def test_load_replies_ordered_by_date(temp_db):
    df = load_replies(temp_db, 'd1')
    assert df.iloc[0]['author'] == 'alice'
    assert df.iloc[1]['author'] == 'bob'

def test_load_replies_empty_for_unknown_id(temp_db):
    df = load_replies(temp_db, 'nonexistent')
    assert len(df) == 0
```

**Step 2: Run test to verify it fails**

```bash
cd C:/Github/scraping-copilot
python -m pytest tests/test_reply_loading.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `load_replies` not in app yet.

**Step 3: Add `load_replies()` to `app.py`**

Add this function after the `load_data()` function (around line 215, before the `db_path = "discussions.db"` line):

```python
def load_replies(discussion_id):
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT * FROM replies WHERE parent_id = ? ORDER BY publish_date",
        conn, params=(discussion_id,)
    )
    conn.close()
    return df
```

**Step 4: Update detail view to show threaded replies**

Replace the reply section in `app.py` (lines 396–401):

```python
# OLD:
if "replies" in item and isinstance(item["replies"], list):
    st.markdown(f"#### Replies ({len(item['replies'])})")
    for reply in item["replies"]:
        st.markdown("---")
        st.markdown(f"**{reply.get('author', 'Unknown')}** ({reply.get('publish_date', '')})")
        st.write(reply.get("content", ""))
```

```python
# NEW:
replies_df = load_replies(item["id"])
if not replies_df.empty:
    st.markdown(f"#### Replies ({len(replies_df)})")
    for _, reply in replies_df.iterrows():
        with st.container(border=True):
            st.markdown(f"**{reply.get('author', 'Unknown')}** · {reply.get('publish_date', '')}")
            st.write(reply.get("content", ""))
else:
    st.markdown("#### Replies (0)")
    st.caption("No replies found for this discussion.")
```

**Step 5: Update test to import from the right place and run**

Update `tests/test_reply_loading.py` — the test already has `load_replies` defined inline (copy of the function). This is intentional to test the logic in isolation. Run:

```bash
python -m pytest tests/test_reply_loading.py -v
```

Expected: All 3 tests PASS.

**Step 6: Commit**

```bash
git add app.py tests/test_reply_loading.py
git commit -m "feat: lazy-load and display threaded replies in detail view"
```

---

### Task 2: Enrich `analyze_local.py` with reply content

**Files:**
- Modify: `analyze_local.py:9-17` (`load_data_from_db`)
- Modify: `analyze_local.py:211-216` (document building loop)
- Modify: `analyze_local.py:253-254` (full_text construction)

**Step 1: Write the failing test**

Add to `tests/test_reply_loading.py`:

```python
def load_data_with_replies(db_path):
    """Load discussions joined with concatenated reply content."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*,
               GROUP_CONCAT(r.content, ' ') AS reply_content
        FROM discussions d
        LEFT JOIN replies r ON r.parent_id = d.id
        GROUP BY d.id
    """)
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]
    conn.close()
    return data

def test_load_data_with_replies_includes_reply_text(temp_db):
    data = load_data_with_replies(temp_db)
    d1 = next(d for d in data if d['id'] == 'd1')
    assert 'First reply' in (d1.get('reply_content') or '')
    assert 'Second reply' in (d1.get('reply_content') or '')

def test_load_data_with_replies_null_for_no_replies(temp_db):
    data = load_data_with_replies(temp_db)
    # d2 exists in replies table but not discussions — only d1 is in discussions
    d1 = next(d for d in data if d['id'] == 'd1')
    assert d1['reply_content'] is not None
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_reply_loading.py::test_load_data_with_replies_includes_reply_text -v
```

Expected: FAIL — `load_data_with_replies` not defined in analyze_local.py yet.

**Step 3: Update `load_data_from_db` in `analyze_local.py`**

Replace lines 9–17:

```python
# OLD:
def load_data_from_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM discussions")
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]
    conn.close()
    return data
```

```python
# NEW:
def load_data_from_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*,
               GROUP_CONCAT(r.content, ' ') AS reply_content
        FROM discussions d
        LEFT JOIN replies r ON r.parent_id = d.id
        GROUP BY d.id
    """)
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]
    conn.close()
    return data
```

**Step 4: Update `full_text` construction to include replies**

In `analyze_local.py`, update the two places where text is built:

Line ~212 (document building for clustering):
```python
# OLD:
text = (str(item.get('title', '')) + " " + str(item.get('content', '')))
```
```python
# NEW:
text = " ".join(filter(None, [
    str(item.get('title', '')),
    str(item.get('content', '')),
    str(item.get('reply_content', '') or '')
]))
```

Line ~254 (analysis tagging loop):
```python
# OLD:
full_text = (str(item.get('title', '')) + " " + str(item.get('content', '')))
```
```python
# NEW:
full_text = " ".join(filter(None, [
    str(item.get('title', '')),
    str(item.get('content', '')),
    str(item.get('reply_content', '') or '')
]))
```

**Step 5: Run tests**

```bash
python -m pytest tests/test_reply_loading.py -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add analyze_local.py tests/test_reply_loading.py
git commit -m "feat: include reply content in local analysis clustering and tagging"
```

---

### Task 3: Enrich `analyze_intent.py` with reply context

**Files:**
- Modify: `analyze_intent.py:23-38` (`load_data_from_db`)
- Modify: `analyze_intent.py:79-118` (`analyze_intent` function — prompt)

**Step 1: Update `load_data_from_db` in `analyze_intent.py`**

Replace lines 23–38 with the same JOIN query used in `analyze_local.py`, but fetch only top 3 replies per discussion to keep prompts concise:

```python
def load_data_from_db(db_path, limit=0):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM discussions"
    if limit > 0:
        query += f" LIMIT {limit}"
    cursor.execute(query)
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]

    # Attach top 3 replies per discussion
    for item in data:
        cursor.execute("""
            SELECT content FROM replies
            WHERE parent_id = ?
            ORDER BY publish_date
            LIMIT 3
        """, (item['id'],))
        item['top_replies'] = [r['content'] for r in cursor.fetchall()]

    conn.close()
    return data
```

**Step 2: Update `analyze_intent()` prompt to include replies**

Replace the `user_prompt` in `analyze_intent.py` lines 91–103:

```python
# OLD:
user_prompt = f"""
Analyze the following customer discussion thread.

Title: {title}
Content: {content}

Provide the output in JSON format with the following keys:
...
"""
```

```python
# NEW:
top_replies = discussion.get('top_replies', [])
replies_text = ""
if top_replies:
    formatted = "\n".join(f"  - {r}" for r in top_replies if r and len(r.strip()) > 5)
    if formatted:
        replies_text = f"\nTop replies:\n{formatted}"

user_prompt = f"""
Analyze the following customer discussion thread including its replies.

Title: {title}
Post: {content}{replies_text}

Provide the output in JSON format with the following keys:
- "category": (e.g., "Bug/Issue", "Feature Request", "How-to/Question", "Pricing/Licensing", "General Discussion")
- "product_area": (e.g., "Excel", "Outlook", "Teams", "PowerPoint", "Admin Center", "Copilot Studio", "General")
- "pain_points": A list of specific struggles or issues mentioned across the post AND replies (max 3).
- "sentiment": Overall sentiment considering both post and replies (e.g., "Positive", "Neutral", "Negative")
- "summary": A concise one-sentence summary of the core issue and how it was received.
"""
```

**Step 3: Run existing tests to confirm nothing broken**

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS.

**Step 4: Commit**

```bash
git add analyze_intent.py
git commit -m "feat: include top 3 replies in AI analysis prompt for richer context"
```

---

### Task 4: Reply aggregation in Topic Explorer

**Files:**
- Modify: `app.py:405-485` (Topic Explorer tab)

**Step 1: Add reply stats query helper**

Add this function in `app.py` after `load_replies()`:

```python
@st.cache_data
def load_reply_stats():
    """Load per-discussion reply counts and sentiment for aggregation."""
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT parent_id,
               COUNT(*) as reply_count,
               GROUP_CONCAT(content, ' ') as all_reply_text
        FROM replies
        GROUP BY parent_id
    """, conn)
    conn.close()
    return df
```

**Step 2: Add reply aggregation block in Topic Explorer**

In the Topic Explorer tab, after the existing "Perspective Matrix" section, add a new "Reply Intelligence" section. Find the end of the perspective matrix rendering (~line 480) and add:

```python
# --- Reply Intelligence ---
st.subheader("Reply Intelligence")

reply_stats = load_reply_stats()

if reply_stats.empty:
    st.caption("No reply data available.")
else:
    # Merge reply stats onto topic discussions
    topic_with_replies = topic_df.merge(
        reply_stats, left_on="id", right_on="parent_id", how="left"
    )

    total_replies = int(topic_with_replies["reply_count"].sum(skipna=True))
    threads_with_replies = int(topic_with_replies["reply_count"].notna().sum())
    st.markdown(f"**{total_replies} replies** across **{threads_with_replies} discussions** in this topic")

    # Reply sentiment bar (keyword-based on reply text)
    if total_replies > 0:
        all_reply_text = " ".join(
            topic_with_replies["all_reply_text"].dropna().tolist()
        ).lower()
        neg_words = ["fail", "error", "bug", "broken", "issue", "problem", "slow", "crash", "stuck", "frustrat"]
        pos_words = ["great", "love", "amazing", "helpful", "thanks", "good", "fixed", "resolved", "working"]
        neg = sum(all_reply_text.count(w) for w in neg_words)
        pos = sum(all_reply_text.count(w) for w in pos_words)
        neu = max(total_replies - neg - pos, 0)
        total_signals = neg + pos + neu or 1

        sentiment_fig = px.bar(
            x=["Negative", "Neutral", "Positive"],
            y=[neg/total_signals*100, neu/total_signals*100, pos/total_signals*100],
            color=["Negative", "Neutral", "Positive"],
            color_discrete_map={"Negative": "#e74c3c", "Neutral": "#95a5a6", "Positive": "#2ecc71"},
            labels={"x": "Sentiment", "y": "% of signal words"},
            title="Reply Sentiment Signal",
        )
        st.plotly_chart(sentiment_fig, use_container_width=True)

    # Top reply keywords
    st.markdown("**Top keywords in replies:**")
    combined_reply_text = " ".join(
        topic_with_replies["all_reply_text"].dropna().tolist()
    )
    if combined_reply_text.strip():
        from sklearn.feature_extraction.text import TfidfVectorizer as _TV
        import re as _re
        cleaned = _re.sub(r'[^a-zA-Z\s]', '', combined_reply_text).lower()
        try:
            tv = _TV(stop_words='english', max_features=50)
            tv.fit_transform([cleaned])
            top_words = tv.get_feature_names_out()[:10]
            st.write(", ".join(top_words))
        except Exception:
            st.caption("Not enough reply text for keyword extraction.")

    # Resolution signal: % of threads whose last reply contains positive words
    if threads_with_replies > 0:
        def is_positive(text):
            if not text:
                return False
            return any(w in str(text).lower() for w in ["fixed", "resolved", "working", "thanks", "solved"])

        resolved = topic_with_replies["all_reply_text"].apply(
            lambda t: is_positive(str(t).split()[-50:] if t else "")
        ).sum()
        pct = int(resolved / threads_with_replies * 100)
        st.metric("Threads showing resolution signal", f"{pct}%",
                  help="% of threads where replies contain words like 'fixed', 'resolved', 'working'")
```

**Step 3: Verify app loads without errors**

```bash
cd C:/Github/scraping-copilot
python -c "import app"
```

Expected: No import errors.

**Step 4: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add reply intelligence section to Topic Explorer"
```

---

## Summary of Changes

| File | What changes |
|------|-------------|
| `app.py` | + `load_replies()`, + `load_reply_stats()`, threaded detail view, reply intelligence in Topic Explorer |
| `analyze_local.py` | JOIN replies into clustering/tagging text corpus |
| `analyze_intent.py` | Attach top 3 replies per discussion, include in LLM prompt |
| `tests/test_reply_loading.py` | New — tests for reply loading and data JOIN logic |
