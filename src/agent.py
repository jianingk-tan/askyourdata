"""
agent.py — The agentic loop.

Architecture:
  1. User asks a natural-language question
  2. Claude generates a SQL query via the `run_sql` tool
  3. We execute the query (with safety checks) and return results
  4. If the query failed, Claude sees the error and self-corrects (loop)
  5. Once the query succeeds, Claude synthesizes a business insight

This is a true agent loop — not a single-shot LLM call. The model can iterate,
react to errors, and decide when it has enough information to answer.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from src.sql_tools import get_schema, run_sql_safe

load_dotenv()

# Model selection — claude-sonnet-4-6 hits the best price/quality ratio for this task.
# Swap to "claude-opus-4-7" if you want the very best (and don't mind ~5x cost).
MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_AGENT_ITERATIONS = 5

SYSTEM_PROMPT_TEMPLATE = """You are AskYourData, an AI data analyst.

You help non-technical business users get answers from the classic Northwind
sample database — a small-business ERP with customers, orders, products,
suppliers, employees, and shippers.

When a user asks a question:

1. Think briefly about which tables you need
2. Call the `run_sql` tool with a valid SQLite SELECT query
3. Review the result
4. If the result is wrong, empty, or the query errored, try a different query
5. Once you have the data you need, write a clear, concise business insight

RULES:
- Only generate SELECT statements (no INSERT/UPDATE/DELETE/etc.)
- Use SQLite syntax (date functions: strftime, date('now'), julianday)
- The "Order Details" table contains a SPACE — quote it: FROM "Order Details"
- Revenue per line item = Quantity * UnitPrice * (1 - Discount)
- Always aggregate or LIMIT when fetching from large tables (Orders has 16K rows,
  Order Details has 600K rows)
- Do NOT select binary columns (Photo, Picture) — they're hidden from your schema
  but if you SELECT * you'll get junk
- When you write the final answer, focus on business meaning, not SQL mechanics
- Do not include the SQL inside your final natural-language answer — the user
  sees it separately

DATA TIME WINDOW:
Order dates range from 2012 to 2023. When the user asks about "last month"
or "this year," interpret it relative to the latest order date in the data,
which is 2023-10-28. You may query MAX(OrderDate) first if you need to be precise.

DATABASE SCHEMA:

{schema}
"""


TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "Execute a read-only SQLite SELECT query against the e-commerce database. "
            "Returns the results as JSON with columns, rows, and row count. "
            "If the query fails, returns an error message that you can use to fix the query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A valid SQLite SELECT statement.",
                }
            },
            "required": ["query"],
        },
    }
]


@dataclass
class AgentResult:
    """Structured response that the UI layer can render."""

    final_answer: str
    sql_queries: list[str] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    error: str | None = None

    @property
    def last_successful_result(self) -> dict[str, Any] | None:
        """Most recent tool result that didn't error — for charting in the UI."""
        for result in reversed(self.tool_results):
            if "error" not in result:
                return result
        return None


def ask_agent(user_question: str, model: str = MODEL_NAME) -> AgentResult:
    """
    Run the agent loop until Claude produces a final natural-language answer
    (or we hit the iteration limit).
    """
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env automatically

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=get_schema())
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_question}]

    result = AgentResult(final_answer="")

    for iteration in range(MAX_AGENT_ITERATIONS):
        result.iterations = iteration + 1

        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as exc:
            result.error = f"API call failed: {exc}"
            result.final_answer = (
                "I couldn't reach the Claude API. Please check your API key and try again."
            )
            return result

        # --- Branch 1: model wants to call a tool ---
        if response.stop_reason == "tool_use":
            # Append assistant turn (with tool_use block) to history
            messages.append({"role": "assistant", "content": response.content})

            # Find and execute every tool_use block in the response
            tool_result_blocks = []
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "run_sql":
                        query = block.input["query"]
                        result.sql_queries.append(query)
                        tool_output = run_sql_safe(query)
                        result.tool_results.append(tool_output)

                        # JSON-stringify the result for the model
                        tool_result_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(tool_output, default=str),
                        })
                    else:
                        tool_result_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Unknown tool: {block.name}",
                            "is_error": True,
                        })

            # Send tool results back so the model can continue
            messages.append({"role": "user", "content": tool_result_blocks})
            continue

        # --- Branch 2: model gave a final text answer ---
        if response.stop_reason in ("end_turn", "stop_sequence"):
            answer_parts = [b.text for b in response.content if b.type == "text"]
            result.final_answer = "\n".join(answer_parts).strip()
            return result

        # --- Branch 3: something unexpected ---
        result.error = f"Unexpected stop_reason: {response.stop_reason}"
        result.final_answer = "The agent stopped unexpectedly. Please try rephrasing your question."
        return result

    # Loop exhausted without producing an answer
    result.error = "Agent exceeded maximum iterations."
    result.final_answer = (
        "I tried several approaches but couldn't reach a confident answer. "
        "Could you try rephrasing your question or making it more specific?"
    )
    return result


# Allow running the agent from the command line for quick testing
if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "Which 5 customers brought in the most revenue?"
    print(f"\n❓  {question}\n")

    out = ask_agent(question)

    print(f"📋  Agent ran {out.iterations} iteration(s)")
    for i, sql in enumerate(out.sql_queries, start=1):
        print(f"\n--- SQL #{i} ---")
        print(sql)

    print(f"\n💡  Answer:\n{out.final_answer}\n")

    if out.error:
        print(f"⚠️   Error: {out.error}")
