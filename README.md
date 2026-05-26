# AskYourData 📊

> An AI agent that turns plain-English questions into SQL queries, validates them, and explains the results in business terms.

**Live demo:** _add your Streamlit Cloud URL here_
**Author:** Jianing Tan · [LinkedIn](#) · [Email](mailto:jianing.tan@outlook.com)

---

## What it does

Ask a question like _"Which 5 customers brought in the most revenue?"_ and the agent will:

1. Decide which tables it needs from the schema
2. Write a SQLite `SELECT` query
3. Validate the query against an allowlist (only `SELECT`, no stacked statements, no DDL)
4. Execute it against a read-only database connection
5. If the query errored, **self-correct** and try again (true agent loop, not single-shot)
6. Synthesize the result into a written business insight
7. Auto-generate the most appropriate chart (bar / line / scatter) based on result shape

The SQL is shown transparently so users can verify the agent's reasoning.

---

## Why I built this

I wanted hands-on experience with the patterns that production AI systems actually use:

- **Tool use / function calling** — not prompting tricks, real structured tool invocation
- **Agent loops with self-correction** — letting the model see errors and recover, rather than failing on the first bad output
- **Safety boundaries** — the LLM cannot do anything destructive, by construction
- **Two-stage reasoning** — separate calls for query generation and insight synthesis
- **Schema injection** — the model is grounded in the actual database structure rather than guessing table names

These are the exact building blocks behind tools like Cursor, Claude Code, and modern enterprise AI assistants.

---

## Architecture

```
┌─────────────────┐
│  User question  │
└────────┬────────┘
         ▼
┌──────────────────────┐
│  Claude (Sonnet 4.6) │  System prompt injects the full schema
│  + tool_use API      │
└────────┬─────────────┘
         │ generates SQL
         ▼
┌──────────────────────┐
│  Safety layer        │  sqlparse + keyword allowlist
│  (sql_tools.py)      │  Read-only SQLite connection (mode=ro)
└────────┬─────────────┘
         │ result OR error
         ▼
┌──────────────────────┐
│  Agent loop          │  On error → return to Claude for retry
│  (agent.py)          │  Max 5 iterations
└────────┬─────────────┘
         │ final answer
         ▼
┌──────────────────────┐
│  Streamlit UI        │  Insight + table + auto-chart + SQL transparency
│  (app.py)            │
└──────────────────────┘
```

---

## Tech stack

- **Python 3.11+**
- **Anthropic Python SDK** (Claude with tool use)
- **SQLite** + **sqlparse** for validation
- **Streamlit** for the UI
- **Plotly** for auto-visualization
- **pandas** for data handling

No LangChain, no vector DBs, no orchestration framework — just the Anthropic SDK and a clean agent loop, ~250 lines of agent code total.

---

## Run it locally

```bash
# 1. Clone & enter
git clone https://github.com/YOUR-USERNAME/askyourdata.git
cd askyourdata

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# then edit .env and paste your key from https://console.anthropic.com/

# 4. Build the sample database (one-time)
python scripts/init_db.py

# 5. (Optional) Audit the data
python scripts/audit_data.py

# 6. (Optional) Run the smoke tests
python smoke_test.py

# 7. Launch the app
streamlit run app.py
```

You can also run the agent from the command line:

```bash
python -m src.agent "Which sales rep closed the most deals in 2025?"
```

---

## The dataset

This uses Microsoft's classic **Northwind sample database**, ported to SQLite by [jpwhite3/northwind-SQLite3](https://github.com/jpwhite3/northwind-SQLite3) (MIT-licensed). Northwind is the canonical small-business ERP dataset — used in countless SQL tutorials, courses, and certification exams.

Key tables the agent works with:

| Table | Rows | Description |
|---|---|---|
| `Customers` | 93 | Companies and contacts across 21 countries |
| `Orders` | 16,282 | Order header — customer, employee, shipper, dates, freight |
| `Order Details` | 609,283 | Order line items with quantity, unit price, and discount |
| `Products` | 77 | Across 8 categories — Beverages, Condiments, Dairy, etc. |
| `Employees` | 9 | Sales reps and managers |
| `Suppliers` | 29 | Across 16 countries |
| `Shippers` | 3 | Logistics providers |
| `Categories` | 8 | Product taxonomy |

The order date range is **July 2012 – October 2023**, so "this month" / "last year" queries are interpreted relative to the data's actual time window, not real-world today.

`scripts/init_db.py` downloads the database (~24 MB) on first run. After download, it's cached locally — subsequent runs are instant.

---

## Data audit & cleaning

Before connecting the agent to this dataset, I ran a six-pass audit. The full findings are in [`AUDIT_REPORT.md`](AUDIT_REPORT.md), regenerable any time with:

```bash
python scripts/audit_data.py              # print to terminal
python scripts/audit_data.py --markdown   # also regenerate AUDIT_REPORT.md
```

The audit covers six dimensions:

1. **Structural** — table sizes and emptiness
2. **BLOB risk** — binary columns that could blow up the LLM's token budget
3. **NULL distribution** — missing data in key columns
4. **Type quirks** — values that don't match declared types
5. **Referential integrity** — orphan records across foreign keys
6. **Business rules** — sanity checks on quantities, dates, ranges

### What I found and how I addressed it

Rather than dump every issue into a "cleaning script" and silently mutate the data, I used a **three-layer defense** strategy:

| Layer | What it does | Examples |
|---|---|---|
| **Prompt** | The agent is told about quirks upfront | "`Order Details` has a space — quote it"; "`Discontinued` is TEXT `'0'`/`'1'`"; "data ends 2023-10-28" |
| **Schema** | Hidden tables/columns the agent never sees | Empty demographic tables; `Photo` and `Picture` BLOB columns |
| **Result** | Final filter before data leaves SQLite | BLOB columns auto-stripped even on `SELECT *` |

### What I deliberately did NOT "clean"

- **NULL columns kept as-is** — `ShippedDate IS NULL` means "not shipped yet," not "missing data." `Employees.ReportsTo IS NULL` means CEO. Imputing would destroy real business signal.
- **Date timestamps left at 2023** — I could have shifted everything forward to make the data "current," but lying to the user about data freshness is worse than honestly disclosing the window.
- **No fake data added to empty tables** — `CustomerDemographics` is 0 rows. Synthesizing rows to "fix" it would be data fabrication.

---

## Sample questions to try

- _Which 5 customers brought in the most revenue?_
- _What's the average order value by country?_
- _Which employee closed the most orders?_
- _Show me monthly revenue for the most recent 12 months in the data_
- _Which product categories generate the highest revenue?_
- _Which suppliers ship from outside North America?_
- _What's the most expensive product that's currently discontinued?_

---

## Safety design

The agent **cannot** modify, drop, or exfiltrate data, because:

1. The validator (`src/sql_tools.py`) rejects anything that isn't a single `SELECT` statement
2. A keyword allowlist catches `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `REPLACE`, `ATTACH`, `DETACH`, `PRAGMA`, `VACUUM`
3. Multi-statement queries (`SELECT ...; DELETE ...`) are rejected at parse time
4. The DB connection opens in SQLite read-only mode (`?mode=ro`)
5. Result size is capped at 100 rows to prevent token blowup

The smoke tests in `smoke_test.py` cover all of these.

---

## File layout

```
askyourdata/
├── app.py                  Streamlit UI
├── scripts/
│   ├── init_db.py          Downloads the Northwind SQLite DB (~24 MB)
│   └── audit_data.py       Six-pass data quality audit
├── src/
│   ├── agent.py            Agent loop (tool use + self-correction)
│   ├── sql_tools.py        Schema introspection, validation, execution
│   └── visualizer.py       Auto-chart heuristics
├── smoke_test.py           Mocked end-to-end tests
├── data/                   Downloaded DB lives here (gitignored)
├── AUDIT_REPORT.md         Committed audit findings (regenerable)
├── requirements.txt
├── .env.example
└── README.md
```

---

## License

MIT
