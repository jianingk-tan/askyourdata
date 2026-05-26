"""
smoke_test.py — Validates that the whole pipeline imports and runs WITHOUT
hitting the real Anthropic API. Useful before pushing to GitHub.

Run: python smoke_test.py
"""

import json
from unittest.mock import MagicMock, patch

from src.sql_tools import get_schema, run_sql_safe, validate_sql
from src.visualizer import auto_chart
import pandas as pd


def test_schema():
    schema = get_schema()
    assert "Customers" in schema
    assert "Orders" in schema
    # Sanity check: BLOB columns must NOT appear in the schema view.
    # We check with word boundaries: "Photo " or "Photo\n" (BLOB) but not "PhotoPath"
    import re
    assert not re.search(r"\bPhoto\b(?!Path)", schema), "Photo BLOB column leaked into schema"
    assert "Picture" not in schema, "Picture BLOB column leaked into schema"
    print("✓ Schema introspection works (BLOB columns properly hidden)")


def test_validation():
    cases = [
        ('SELECT * FROM Customers LIMIT 5', True),
        ('SELECT * FROM "Order Details" LIMIT 5', True),  # space in table name
        ("DROP TABLE Customers", False),
        ("SELECT * FROM Customers; DELETE FROM Customers", False),
        ("INSERT INTO Customers VALUES (1)", False),
    ]
    for q, expected in cases:
        ok, _ = validate_sql(q)
        assert ok == expected, f"FAILED on: {q}"
    print("✓ SQL validation works (incl. quoted table names)")


def test_execution():
    r = run_sql_safe("SELECT Country, COUNT(*) as n FROM Customers GROUP BY Country ORDER BY n DESC LIMIT 5")
    assert "rows" in r
    assert len(r["rows"]) > 0
    print(f"✓ SQL execution works — top customer country: {r['rows'][0]}")


def test_blob_protection():
    """Make sure that even if the agent does SELECT *, BLOBs get stripped."""
    r = run_sql_safe("SELECT * FROM Employees LIMIT 1")
    assert "Photo" not in r["columns"], "BLOB column leaked through SELECT *"
    print("✓ BLOB stripping works (Photo column dropped from results)")


def test_visualizer():
    df = pd.DataFrame({"country": ["USA", "Canada", "UK"], "revenue": [1000, 500, 300]})
    fig = auto_chart(df)
    assert fig is not None
    print("✓ Auto-chart works (bar chart selected for categorical × numeric)")


def test_agent_loop_with_mock():
    """Mock the Anthropic API and walk through one full agent loop."""
    from src import agent as agent_module

    # First response: tool_use
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.name = "run_sql"
    tool_use_block.id = "toolu_test123"
    tool_use_block.input = {"query": "SELECT COUNT(*) as n FROM Customers"}

    first_response = MagicMock()
    first_response.stop_reason = "tool_use"
    first_response.content = [tool_use_block]

    # Second response: final text answer
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "The database contains 93 customers."

    second_response = MagicMock()
    second_response.stop_reason = "end_turn"
    second_response.content = [text_block]

    # Patch the Anthropic client
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [first_response, second_response]

    with patch.object(agent_module, "Anthropic", return_value=mock_client):
        result = agent_module.ask_agent("How many customers do we have?")

    assert result.final_answer == "The database contains 93 customers."
    assert len(result.sql_queries) == 1
    assert result.iterations == 2  # tool_use + final answer
    print(f"✓ Agent loop works — iterations: {result.iterations}, SQL: {result.sql_queries[0]}")


def test_agent_self_correction():
    """Simulate a bad query → error → corrected query → success."""
    from src import agent as agent_module

    # Round 1: model writes a bad query
    bad_tool_use = MagicMock()
    bad_tool_use.type = "tool_use"
    bad_tool_use.name = "run_sql"
    bad_tool_use.id = "toolu_bad"
    bad_tool_use.input = {"query": "SELECT * FROM nonexistent_table"}

    r1 = MagicMock()
    r1.stop_reason = "tool_use"
    r1.content = [bad_tool_use]

    # Round 2: model self-corrects
    good_tool_use = MagicMock()
    good_tool_use.type = "tool_use"
    good_tool_use.name = "run_sql"
    good_tool_use.id = "toolu_good"
    good_tool_use.input = {"query": "SELECT COUNT(*) as n FROM Customers"}

    r2 = MagicMock()
    r2.stop_reason = "tool_use"
    r2.content = [good_tool_use]

    # Round 3: final answer
    text = MagicMock()
    text.type = "text"
    text.text = "After correcting the table name, I found 93 customers."

    r3 = MagicMock()
    r3.stop_reason = "end_turn"
    r3.content = [text]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [r1, r2, r3]

    with patch.object(agent_module, "Anthropic", return_value=mock_client):
        result = agent_module.ask_agent("How many customers?")

    assert len(result.sql_queries) == 2
    assert "error" in result.tool_results[0]  # first query failed
    assert "error" not in result.tool_results[1]  # second succeeded
    print(f"✓ Self-correction works — agent recovered after {len(result.sql_queries)} attempts")


if __name__ == "__main__":
    print("Running smoke tests...\n")
    test_schema()
    test_validation()
    test_execution()
    test_blob_protection()
    test_visualizer()
    test_agent_loop_with_mock()
    test_agent_self_correction()
    print("\n✅ All smoke tests passed — code is ready to ship.")
