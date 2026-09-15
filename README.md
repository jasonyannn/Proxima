# Proxima — Product Management Agent

Turn customer feedback into structured product decisions, compare your product
against competitors, and triage copyright/IP risk before you build.

Proxima is a **Python + Streamlit** app. It is not a Node project — `npm run dev`
works, but only as a thin wrapper around `run.sh`.

---

## Running it

```bash
npm run dev          # or: ./run.sh
```

Then open <http://localhost:8501>.

The script is self-bootstrapping: it creates `.venv`, installs dependencies from
`proxima/proxima/requirements.txt` on first run (and whenever that file changes),
and launches Streamlit.

```bash
npm test             # run the analyser test suite (30 tests)
```

### Optional: the LLM

The chat agent talks to a local [Ollama](https://ollama.com) server:

```bash
ollama serve
ollama pull llama3.2
```

Without it the app still runs — chat falls back to rule-based replies, and both
analysers work fully, since neither depends on the model.

---

## Using it from your editor

Proxima also runs as an [MCP](https://modelcontextprotocol.io) server, so the
backlog, the competitor comparison and the copyright check are available to VS
Code, Claude, Codex and anything else that speaks the protocol — while you are
writing the code they describe.

```bash
./mcp.sh                       # stdio, what editors launch
./mcp.sh --transport http      # http://127.0.0.1:8765/mcp
./mcp.sh --read-only           # analysis only, nothing can write
```

VS Code and Claude Code are configured already ([.vscode/mcp.json](.vscode/mcp.json),
[.mcp.json](.mcp.json)). **[docs/mcp.md](docs/mcp.md)** has the rest: Claude
Desktop, Codex, running alongside the Figma and Supabase servers, what it would
take to host it, and the auth on the HTTP transport.

Like `run.sh`, `mcp.sh` bootstraps its own virtualenv — a client can point at it
on a machine where nobody has run the app yet.

---

## What's in the app

Three tabs:

### 💬 Chat
The original agent. Describe customer feedback in plain language; it classifies
the input as a feature, bug or piece of feedback, writes it to SQLite, and replies.

### 📊 Competitor Comparison
Matches your shipped features against each competitor's and shows:

- **Headline scores** per competitor — how much of their surface you cover, how
  many of their features you have no answer for, and a Low/Moderate/High threat read.
- **Feature coverage matrix** — your features down the side, competitors across
  the top: ✅ they have it, 🟡 partial equivalent, ❌ you're alone here.
- **Gaps to close**, labelled by pressure: *Table stakes* (everyone ships it),
  *Emerging* (more than one), *Single-vendor bet* (one).
- **Your differentiators** — features no competitor has a strong equivalent for.
- **"Ask Proxima for a strategic read"** — feeds the analysis to the LLM for a
  prioritisation recommendation.

Competitors and their features are editable in-app (*Manage competitors*), or you
can load a sample catalogue from the sidebar to see how it behaves.

### ⚖️ Copyright Analyser
Checks a feature you're about to build against the competitor material in the
workspace.

The important design decision: **copyright protects expression, not ideas.**
Building a dark mode because a rival has one is normal competition; shipping
their help-centre copy word-for-word is not. So it scores three axes separately
rather than emitting one meaningless "similarity" percentage:

| axis | high value means | legal flavour |
|---|---|---|
| **concept** | same job, same market | not copyright; *possibly* patent, for novel methods |
| **expression** | the wording tracks theirs | the actual copyright signal — dominates the score |
| **name** | confusable branding | trademark, not copyright |

A feature that is concept-identical but expression-distinct is the normal,
low-risk case, and the report says so explicitly instead of alarming you.

It also flags:
- verbatim word-runs (quoted back to you as evidence),
- specs written as "clone X" / "pixel-perfect copy of Y" — intent language that
  is damaging evidence in a dispute,
- mentions of directly copyrightable assets (icon sets, artwork, fonts, source
  code, stylesheets, documentation).

Output is a 0–100 score, a Low/Moderate/Elevated/High level, itemised findings
with evidence, and concrete recommended actions. Every assessment is saved to
the history table.

> **Not legal advice.** It only sees the competitor text stored in this
> workspace, and it is not a patent, trademark or registered-copyright search.
> Treat a high score as "route this past counsel", never as a verdict.

---

## Layout

```
run.sh                      bootstrap + launch
mcp.sh                      bootstrap + launch the MCP server
package.json                npm wrappers so `npm run dev` works
.mcp.json                   Claude Code picks this up from the repo root
.streamlit/config.toml      headless mode (skips the first-run email prompt)
docs/mcp.md                 connecting the MCP server to each client
proxima/
  product_manager.py        standalone backlog/prioritisation helpers
  tests/test_analysis.py    30 tests, incl. the similarity calibration set
  proxima/
    app.py                  Streamlit UI (3 tabs)
    agent.py                intent classification + Ollama client
    database.py             SQLite schema and CRUD
    prompt.py               system prompt
    textsim.py              similarity engine (concept / expression / name)
    competitors.py          coverage matrix, gap analysis, threat scoring
    copyright_analyzer.py   IP risk model
    seed_data.py            sample competitor catalogue
    mcp_server/             the same analysers, over MCP
    data/product.db         created on first run
```

### How matching works

`textsim.py` is deliberately dependency-free — no embeddings, no network. It uses
stemming, a small product-domain synonym map (`dark mode` ≈ `dark theme`),
acronym expansion (`SSO` ≈ `single sign-on`), token-set overlap for concept, and
character n-grams plus word-level sequence matching for expression.

The thresholds in `competitors.py` are calibrated against a labelled set of
feature pairs in `tests/test_analysis.py::TestCalibration`. On that set,
unrelated pairs score ~0.0 and same-job pairs score 0.37–1.0, so the thresholds
sit in the empty band between the two clusters. **If you tune the similarity
metric, those tests tell you whether you actually improved it.**

The synonym map errs toward *fewer* entries on purpose: a false match hides a
real competitive gap, which is the more expensive error.

---

## Sample data

The sidebar's *Load sample competitors* button loads three fictional
competitors ("Northwind PM", "Cobalt Board", "Vellum Insights"). These are
illustrative placeholders for demo purposes, **not** researched claims about any
real company. Replace them with your own verified research before relying on any
output.
