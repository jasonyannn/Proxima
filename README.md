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
npm test             # run every suite (119 tests)
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

Five tabs — Chat, Features, Board, and these two analysers:

### 💬 Chat
The original agent. Describe customer feedback in plain language; it classifies
the input as a feature, bug or piece of feedback, writes it to SQLite, and replies.

**It draws, too.** Ask for percentages, a breakdown, a ranking, a comparison or a
flow, and the answer comes back with a real chart, table or diagram rather than a
paragraph of numbers:

> *"…please examine my copyright risk associated with this, what factors are
> copyright and the percentage of copyright."*

The model emits a small typed block and Proxima renders it — Altair for charts,
a dataframe for tables, mermaid for diagrams. See
[Charts, tables and diagrams](#charts-tables-and-diagrams) for how it works and
what it will not do.

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

## Exporting the workspace

The sidebar, under **02 Workspace**, has a **Download PDF report**: one document
holding everything the five tabs hold separately — features with their
priority and impact, the board by sprint, every competitor and their feature
list, each copyright check with its risk score and finding, feedback and bugs,
and the chat transcript that produced all of it.

It is built for someone who will never open Proxima: an investor, a co-founder,
a lawyer reading the IP section. So it is set for paper rather than for the
app's dark instrument panel, and the agent's markdown — headings, bullets,
tables, code — is typeset rather than dumped.

Two things it will not do. It will not invent: a section with no data says so,
because a report that silently drops its empty parts reads as complete. And it
never leaves the machine — the PDF is generated locally by
[reportlab](https://pypi.org/project/reportlab/), the same way everything else
here stays local.

The button is absent, replaced by a line of explanation, until there is
something to compile.


## Projects and memory

A chat is one conversation about one product. A **project** is a folder of them,
and it is what lets Proxima remember a product across a dozen sessions without
mixing it up with an unrelated one.

Create a project from the sidebar; chats inside it are listed under it, and
`New chat` while a project is open starts another chat in that project. Any chat
can be moved between projects from its `⋮` menu.

### The three layers of memory

They are deliberately different things, and only the third one needs a setting:

| Layer | What it is | Scope |
| --- | --- | --- |
| **Workspace** | features, competitors, IP assessments | one SQLite file per chat, written only when you click save |
| **Project memory** | a short brief you write about the product | every chat in the project, every prompt |
| **Recall** | a digest of what was said in other chats | whatever the Memory setting allows |

**Project memory** is the text box inside each project in the sidebar. Write what
the product is once — "a no-code shop builder for independent makers, mobile
first" — and it goes into the prompt for every chat in that project, above
anything recalled from a transcript. It is durable and exact, which is why it
outranks the digest when the two disagree.

**Recall** is the lossy one, and the Memory setting decides how far it reaches:

- **This chat only** — nothing from your other conversations reaches the model.
- **This project** *(default)* — the brief, plus a digest of the other chats
  filed under the same project.
- **All my chats** — a digest of every chat on the account, each line tagged
  with the project it came from.

The default is deliberate. A digest of every conversation on the machine is how
an agent starts answering a question about a shop builder with advice about last
week's analytics tool: nothing tells the model which context it is in, so it
averages them. Chats in a project are about the same product by construction, so
their history is evidence rather than noise. "All my chats" is still there for
when the breadth is what you want.

Two rules that are enforced rather than hoped for, and covered by tests in
`tests/test_projects.py`:

- The open chat is never in its own digest — it is already passed as
  conversation history, and repeating it spends context to say it twice.
- "This project" on a chat that is not in a project recalls **nothing**. It does
  not quietly fall back to everything; the sidebar tells you why it is empty.

Recall is capped at six exchanges and ~1800 characters, whichever comes first.
Local models run with a small context window, and recall is the first thing that
should give.

Everything here stays on this machine. None of it changes the model's weights —
it is recall, not training.

## Charts, tables and diagrams

The model decides *what* the numbers are; `visuals.py` draws them. Nothing is
parsed out of sentences — if it is not in a block, it is prose. The three blocks
are `proxima-chart`, `proxima-table` and `mermaid`:

```proxima-chart
{"kind": "bar", "title": "Risk by factor", "unit": "%",
 "data": [{"label": "Logo similarity", "value": 72}],
 "note": "Estimated, not measured."}
```

### Getting a 3B model to actually use them

Putting the format in the system prompt **did not work**. llama3.2 read it,
ignored it, and wrote a markdown table — by the time it starts answering, the
formatting rules are 3000 characters behind it. Worse, a worked example with real
values (`Logo similarity / 72%`) got copied as *content*: the model returned those
exact labels and numbers for an unrelated product.

Two fixes, both measured rather than assumed:

1. **The reminder goes after the question, not into the system prompt.** When the
   message asks for numbers or a flow, `visuals.turn_reminder()` appends a short
   imperative block-shape to the end of the turn, where the model is still
   looking. This is the deterministic half of the feature.
2. **Every example is schematic** — `<first thing>`, `value: 0` — so there is
   nothing worth copying.

On llama3.2:3b, asking for a chart, a breakdown, a diagram and a table each
produced the right block, with zero malformed blocks. The intent detector is
tested for false positives too: an ordinary question like *"what should I build
next quarter"* demands nothing, because forcing a chart onto a prose answer makes
the model invent numbers to fill it. It may still *volunteer* one when its answer
genuinely is numbers, which is allowed.

### What it will not do

- **A malformed block never costs you the answer.** Trailing commas are repaired,
  `"72%"` is read as `72`, and anything still unparseable is shown as visible text
  with a note saying why — never a traceback mid-reply.
- **A half-written block is held back while streaming.** Only prose streams; the
  blocks are drawn when the fence closes.
- **Estimates are labelled.** The prompt requires the model to say when a number
  is its judgement rather than a measurement, and to point at the Copyright
  Analyser tab for the measured version. It is a language model putting a number
  on a legal question — the chart makes it legible, not correct.

### Chart colours

One series gets one hue (the app accent); several get a fixed categorical order,
never cycled or generated. The palette is validated against the chart surface
`#121620` for lightness band, chroma, colour-vision separation and contrast.
Charts ship with a table view, and a single series carries no legend because the
title names it.

## Accessibility and settings

The rule the settings panel is built to: **a setting that does not change
rendering is worse than no setting at all.** A switch labelled "colour blind
mode" that only stores a flag tells someone their need has been handled when it
has not. Every option below reaches the stylesheet, the chart palette, or the
prompt — and there is a test asserting each one produces an artefact.

Everything is per-account and stored on disk, because an accessibility choice
that resets when you restart the app is its own kind of failure.

### Seeing

| Setting | What it does |
| --- | --- |
| **Text size** | Moves the root font size (14 / 16 / 18 / 21px); Streamlit's own spacing is in `rem`, so the whole UI scales together |
| **Contrast** | Redefines the theme's colour tokens. Every ink/ground pair clears WCAG AA — the test computes the ratios rather than trusting the constants |
| **Reading font** | Swaps the interface to Lexend |
| **Chart colours** | Default / Maximum separation / One hue + labels — see below |
| **Never use colour alone** | Prints values on every mark, dashes each line, opens the table under every chart |

**Chart colours** is the one worth explaining. The default palette *already*
clears the colour-vision separation target for neighbouring marks, so a
different set of hues is not the win people expect. The two things that actually
help are:

- **Maximum separation** caps a chart at three coloured series and folds the
  rest into "Other". Three is not a round number — it is how many of these hues
  stay apart under protanopia and deuteranopia when any two marks can sit side
  by side. A fourth fails that test, which is measurable: run
  `validate_palette.js` on four slots with `--pairs all` and watch it drop to
  ΔE 4.8.
- **One hue + labels** carries identity in lightness alone, which survives every
  kind of colour blindness, and forces the values onto the marks because with
  one hue the colour is carrying nothing.

### Moving

**Motion** (reduced stops animations, transitions and the typing cursor on
answers), **larger click targets** (44px, the WCAG 2.5.5 size), and **visible
keyboard focus** (a high-visibility ring on whatever Tab has landed on).

### Hearing

The honest answer is that there is very little to do here: **Proxima plays no
audio and never puts information in sound alone**, so nothing needs captions.
Voice input is optional and lands in the box as editable text. The one real
setting is **alerts stay until dismissed** — a toast fades after a few seconds,
which is a deadline on reading, and some people cannot meet it.

### What is deliberately not a setting

Written down rather than shipped as a switch that does nothing:

- **Screen-reader labelling** and **tab order** — Streamlit owns the widget DOM;
  the app cannot add ARIA to markup it does not render. What it *can* do is here
  instead: every chart has a table view, every risk colour ships with a word,
  and every diagram keeps its source.
- **Captions** — there is no audio to caption.
- **A colour-blindness filter over the UI** — that is a demo, not an
  accommodation. The palette and the second encoding channel are the parts that
  change what a reader can actually tell apart.

### Ordinary settings

Reply language, **answer length** (brief / balanced / detailed, which reaches
the system prompt), prompt assist, and the memory scope described above.

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
  tests/test_projects.py    25 tests for projects and memory scoping
  tests/test_visuals.py     37 tests for chart/table/diagram blocks
  tests/test_accessibility.py  27 tests, incl. computed WCAG ratios
  tests/test_report.py      32 tests for the PDF report, its charts and markdown
  tests/test_agent_errors.py  15 tests for how a failed generation is explained
  tests/test_accounts.py    14 tests for sign-in and staying signed in
  proxima/
    app.py                  wiring: state, auth, chat operations, tab calls
    sidebar.py              projects, workspace and settings
    tabs/                   one module per tab, each a render(...)
      chat.py               the conversation
      features.py           what is filed, and what the chat implies
      board.py              sprints and tickets
      compare.py            ours against theirs, feature by feature
      copyright.py          IP risk, one feature or the whole workspace
      constants.py          status vocabulary and how each one reads
    agent.py                intent classification + Ollama client
    database.py             SQLite schema and CRUD
    workspace.py            per-chat workspaces, projects, persistence
    memory.py               recall scoping + system-prompt assembly
    visuals.py              chart/table/diagram blocks + intent directives
    accessibility.py        settings that change CSS, palette and prompt
    prompt.py               system prompt
    textsim.py              similarity engine (concept / expression / name)
    competitors.py          coverage matrix, gap analysis, threat scoring
    copyright_analyzer.py   IP risk model
    report.py               the whole workspace compiled to one PDF
    report_blocks.py        charts, tables and diagrams inside an answer
    report_style.py         the report's palette, type and small marks
    theme_css.py            the stylesheet theme.py injects
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

---

## License

Proxima is free and open source software, licensed under the
**[GNU Affero General Public License v3.0](LICENSE)** (AGPL-3.0-only).

In plain terms:

- You can use, study, modify and share Proxima, commercially or not.
- If you distribute a modified version, you must release your changes under the
  same license.
- **If you run a modified version as a network service**, you must offer its
  source to the people using it. This is the clause that separates the AGPL from
  the plain GPL, and it is the reason Proxima uses it: Proxima is a hosted web
  app, so "never distributed, only hosted" would otherwise be a way to build a
  closed product on this code.

Each source file carries an `SPDX-License-Identifier: AGPL-3.0-only` header. The
full license text is in [LICENSE](LICENSE).

Copyright © 2026 Jason Yan.

### Trademark

The AGPL grants rights to the *code*. It grants no rights to the *name*.
**"Proxima"** and the Proxima logo are trademarks of Jason Yan. Forks and
derivative works are welcome, but must not use the Proxima name or logo in a way
that suggests they are the official project or endorsed by it. Please pick your
own name for your fork.

### Contributing

Contributions are welcome. Note that contributions are accepted under the
AGPL-3.0, and the project may ask contributors to sign a Contributor License
Agreement before merging, so that the copyright stays consolidated and the
project retains the option to offer commercial licenses alongside the AGPL.
