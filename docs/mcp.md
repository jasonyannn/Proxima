# Connecting Proxima over MCP

Proxima's analysers are useful while you are writing the code they describe, not
only while you are sitting in the Streamlit app. The MCP server exposes them —
the backlog, the competitor comparison, the copyright check — to any editor or
agent that speaks the Model Context Protocol.

```bash
./mcp.sh                       # stdio, what editors launch
./mcp.sh --transport http      # http://127.0.0.1:8765/mcp
./mcp.sh --read-only           # analysis only, nothing can write
```

`mcp.sh` bootstraps its own virtualenv the way `run.sh` does, so a client can
point straight at it on a machine where nobody has run the app yet.

---

## First: which of these are clients?

The six tools you asked about are not the same kind of thing, and the difference
decides what "connect Proxima" can mean for each.

| | What it is | What you can do |
|---|---|---|
| **VS Code** | MCP client | Connects to Proxima directly ✅ |
| **Claude** (Code & Desktop) | MCP client | Connects to Proxima directly ✅ |
| **Codex** | MCP client | Connects to Proxima directly ✅ |
| **Figma** | MCP **server** (Dev Mode) | Cannot connect *to* Proxima — but sits beside it in the same client ✅ |
| **Supabase** | MCP **server** | Same: sits beside Proxima, does not consume it |
| **Vercel** | MCP server, and a **host** | Can host the HTTP transport — with a storage change first ⚠️ |

An MCP server offers tools; a client consumes them. Figma and Supabase publish
servers, so there is no "add Proxima to Figma" setting to find — the useful
arrangement is the one below, where your editor holds all three at once and can
read a Figma frame, check Proxima for whether that feature is a competitive gap,
and query Supabase, inside one task.

---

## VS Code

Already configured at [.vscode/mcp.json](../.vscode/mcp.json):

```json
{
  "servers": {
    "proxima": {
      "type": "stdio",
      "command": "${workspaceFolder}/mcp.sh",
      "args": []
    }
  }
}
```

Open the Command Palette → **MCP: List Servers** → *proxima* → **Start**. The
tools then appear behind the 🛠 icon in Copilot Chat's agent mode.

> `.vscode/` is listed in `.gitignore` (it arrives there from a Windows
> user-profile template, see the comments in that file). The config works
> locally but will not be committed — teammates need their own copy, or you can
> negate the rule the way `.streamlit/` already is.

## Claude Code

[.mcp.json](../.mcp.json) in the repository root is picked up automatically when
you run `claude` from this directory; it is project-scoped, so it is shared with
anyone who clones the repo. Otherwise:

```bash
claude mcp add proxima -- ./mcp.sh
claude mcp add --transport http proxima http://127.0.0.1:8765/mcp   # HTTP instead
```

## Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` — Desktop does
not inherit a working directory, so this one needs absolute paths:

```json
{
  "mcpServers": {
    "proxima": {
      "command": "/Users/you/Proxima/mcp.sh",
      "args": []
    }
  }
}
```

## Codex

```bash
codex mcp add proxima -- /Users/you/Proxima/mcp.sh
```

or by hand in `~/.codex/config.toml`:

```toml
[mcp_servers.proxima]
command = "/Users/you/Proxima/mcp.sh"
args = []
```

## Figma

Figma's Dev Mode MCP server hands your agent the design; Proxima tells it what
the product already ships and what the competition has. Run both in one client
— in VS Code:

```json
{
  "servers": {
    "proxima": { "type": "stdio", "command": "${workspaceFolder}/mcp.sh" },
    "figma":   { "type": "http",  "url": "http://127.0.0.1:3845/mcp" }
  }
}
```

(Figma's server is started from the desktop app: **Preferences → Enable Dev Mode
MCP server**.) Nothing needs to be configured on the Proxima side — the two
servers never talk to each other, the agent holding both is what joins them up.

## Supabase

Same shape: add Supabase's hosted server alongside Proxima in the same client.

Worth being clear about what this does **not** do — Proxima's data stays in
local SQLite either way. Each chat gets its own file under
`proxima/proxima/data/users/<account>/workspaces/`, which is what keeps one
product's competitors from polluting another's analysis. Putting that in
Supabase is a storage migration in [database.py](../proxima/proxima/database.py),
not an MCP connection, and it is a real piece of work: the workspace-per-chat
model would become a tenant column, and `accounts.py` — which is deliberately a
local-only password file — would want to become Supabase Auth. Ask for it as its
own change if you want it.

## Vercel

The HTTP transport is what you would deploy, and `--stateless` exists for hosts
that do not keep a process alive between requests:

```bash
PROXIMA_MCP_TOKEN=$(openssl rand -hex 32) \
  ./mcp.sh --transport http --host 0.0.0.0 --stateless --allow-host your-app.vercel.app
```

**But do not deploy it as-is.** Proxima writes to SQLite files on local disk, and
a serverless filesystem is ephemeral — every feature your agent files would
survive until that function instance is recycled, then vanish silently, which is
the worst failure mode available. Hosting Proxima needs the Supabase-shaped
change above (or any other networked store) first.

Until then, the honest way to reach a local Proxima from elsewhere is a tunnel:

```bash
PROXIMA_MCP_TOKEN=$(openssl rand -hex 32) ./mcp.sh --transport http --allow-host your-tunnel.example
```

---

## Security

The HTTP transport binds `127.0.0.1` and **refuses to start on any other
interface without `PROXIMA_MCP_TOKEN`** — this server reads and writes a product
backlog, and an unauthenticated endpoint on `0.0.0.0` is an open door to it. With
the token set, every request needs `Authorization: Bearer <token>`.

DNS-rebinding protection is on, which checks the `Host` header, so anything
fronting the server (a tunnel, a proxy) has to be named with `--allow-host`.

`--read-only` is the other half: it registers only the 16 read tools, so an agent
can consult the analysis but cannot touch the backlog. Worth using when you are
pointing something autonomous at it.

Nothing here deletes. There are no delete tools at all — an agent that
mis-parses a sentence should cost you a stray row, not a missing one. Deletion
stays in the app, where a person does it on purpose.

---

## Which account, which workspace

The app answers this with your browser session. An MCP client has none, so:

- **Account** is fixed when the server starts: `--owner you@example.com` (or an
  id, or `$PROXIMA_OWNER`). With exactly one local account it is inferred; with
  two or more the server refuses to guess and lists them.
- **Workspace** is a per-call argument. Unset, it falls back to `--workspace` /
  `$PROXIMA_WORKSPACE`, then to the most recent chat. `list_workspaces` shows
  what is available, and tools accept a workspace *title* as well as its id.

```bash
./mcp.sh --owner you@example.com --workspace chat_3_1789342447.37857
```

---

## The tools

**Workspaces** — `list_workspaces`, `workspace_overview`

**Backlog** — `list_features`, `list_bugs`, `list_feedback`, `add_feature`,
`add_bug`, `add_feedback`, and `triage`, which runs a raw sentence through the
same classifier the chat tab uses and only writes it when you pass `save`.

**Board** — `list_tickets`, `list_sprints`, `add_ticket`, `update_ticket`.
Tickets are work, features are what the product does; they are separate tables
on purpose.

**Competitors** — `list_competitors`, `list_competitor_features`,
`save_competitor`, plus the three analyses: `competitive_position` (threat read
per rival), `coverage_matrix` (your features × their features), and `find_gaps`
(what to close, labelled *Table stakes* / *Emerging* / *Single-vendor bet*).

**Copyright / IP** — `assess_ip_risk` for one feature, `sweep_ip_risk` for every
feature against every competitor, `list_ip_assessments` for the history.

Also two **prompts** (`competitive_review`, `ip_check`) and three **resources**
(`proxima://workspaces`, `proxima://{workspace}/features`,
`proxima://{workspace}/competitors`) for pinning data into a conversation
without a tool call.

### Two things the model will get wrong unless you know them

**A competitor with no features on file scores `Unknown`, not `Low`.** That is
missing research, not a win, and `workspace_overview` lists who is in that state.
The tool descriptions say so, but it is the easiest number here to misread.

**The IP score is text similarity, not law.** It scores concept, expression and
name separately because copyright protects expression, not ideas — a feature
that is concept-identical with independent wording is the normal, low-risk case
and the report says so. Every IP tool ships its disclaimer in the payload rather
than trusting the caller to remember it. Treat a high score as "route this past
counsel", never as a verdict.
