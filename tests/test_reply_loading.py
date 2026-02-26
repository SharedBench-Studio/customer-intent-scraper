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
