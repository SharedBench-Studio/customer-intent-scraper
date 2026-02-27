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
