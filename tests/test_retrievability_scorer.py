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
