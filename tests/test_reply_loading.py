import sqlite3
import pytest
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app import _query_replies


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
    df = _query_replies(temp_db, 'd1')
    assert len(df) == 2
    assert set(df['author'].tolist()) == {'alice', 'bob'}


def test_load_replies_ordered_by_date(temp_db):
    df = _query_replies(temp_db, 'd1')
    assert df.iloc[0]['author'] == 'alice'
    assert df.iloc[1]['author'] == 'bob'


def test_load_replies_empty_for_unknown_id(temp_db):
    df = _query_replies(temp_db, 'nonexistent')
    assert len(df) == 0


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


def test_load_data_with_replies_returns_all_discussions(temp_db):
    data = load_data_with_replies(temp_db)
    # temp_db fixture only has d1 in discussions table
    assert len(data) == 1
    assert data[0]['id'] == 'd1'
