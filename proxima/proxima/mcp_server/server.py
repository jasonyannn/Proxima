"""Proxima as an MCP server: the product-management work, without the browser.

The Streamlit app is one client for Proxima's analysers. This is a second one —
it exposes the same functions over the Model Context Protocol, so an editor or
coding agent can consult the backlog, run the competitor comparison and check a
feature for IP risk while it is working on the code that implements it.

Three rules shaped the tool surface:

*Read is cheap, write is not.* Every read tool is annotated read-only so a
client can run it without asking; every write tool is annotated as a mutation
so it prompts. Nothing here deletes — an agent that mis-parses a sentence
should cost you a stray backlog row, not a missing one.

*One call, one answer.* `find_gaps` returns the analysis, not a handle to page
through. These datasets are a product's feature list, not a warehouse.

*Say what the number means.* The analysers deal in similarity scores that are
easy to over-read, so the tools ship the interpretation alongside the score —
the copyright tools carry their disclaimer in the payload rather than trusting
the caller to remember it.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import proxima_modules as pm
from .context import Context, ResolutionError

READS = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
UPDATES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """\
Proxima turns product conversations into structured decisions: a backlog, a
competitor comparison, and a copyright/IP risk read on features before they get
built.

Work is filed per *workspace* — one per chat in the Proxima app, each with its
own features, competitors and assessments. Call `list_workspaces` first if you
do not know which one the user means; every other tool takes an optional
`workspace` and otherwise uses the most recent chat.

The analysers are text-similarity models, not legal or market research. A high
copyright score means "have someone look at this", never "this infringes".
"""


def _err(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc)}


def build_server(context: Context, name: str = "proxima") -> MCPServer:
    """Assemble the server. Write tools are simply not registered when the
    context is read-only: a tool a client cannot see is a tool it cannot try
    and then report as a failure."""

    server = MCPServer(
        name=name,
        title="Proxima — Product Management Agent",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )

    def store(workspace: str | None):
        return context.database(workspace)

    # ------------------------------------------------------------ workspaces

    @server.tool(
        description=(
            "List the Proxima workspaces on this machine — one per chat, each "
            "with its own features, competitors and IP assessments. Call this "
            "first when you do not know which workspace the user means."
        ),
        annotations=READS,
    )
    def list_workspaces() -> dict[str, Any]:
        try:
            found = context.workspaces()
            return {
                "account": context.owner,
                "default": context.default_id(),
                "workspaces": [
                    {
                        "id": w.id,
                        "title": w.title,
                        "created": w.created,
                        "has_data": w.exists,
                    }
                    for w in found
                ],
            }
        except ResolutionError as exc:
            return _err(exc)

    @server.tool(
        description=(
            "Headline state of one workspace: how many features, bugs, pieces "
            "of feedback, tickets and competitors it holds, and the last IP "
            "assessment run. Cheap orientation before deciding what to read."
        ),
        annotations=READS,
    )
    def workspace_overview(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        assessments = db.list_ip_assessments()
        rivals = db.list_competitors()
        rival_features = db.list_competitor_features()
        researched = {f["competitor_name"] for f in rival_features}
        return {
            "workspace": chat_id,
            "features": len(db.list_features()),
            "bugs": len(db.list_bugs()),
            "feedback": len(db.list_feedback()),
            "tickets": len(db.list_tickets()),
            "sprints": len(db.list_sprints()),
            "competitors": len(rivals),
            # A competitor with no feature list scores as "Unknown", not as a
            # win, so it is worth flagging here rather than in the analysis.
            "competitors_without_features": sorted(
                {c["name"] for c in rivals} - researched
            ),
            "ip_assessments": len(assessments),
            "last_ip_assessment": assessments[0] if assessments else None,
        }

    # --------------------------------------------------------------- backlog

    @server.tool(
        description="Features the product ships or plans to ship, newest first.",
        annotations=READS,
    )
    def list_features(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)
        return {"workspace": chat_id, "features": db.list_features()}

    @server.tool(
        description="Open bugs and their severity, newest first.",
        annotations=READS,
    )
    def list_bugs(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)
        return {"workspace": chat_id, "bugs": db.list_bugs()}

    @server.tool(
        description="Customer feedback captured in this workspace, newest first.",
        annotations=READS,
    )
    def list_feedback(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)
        return {"workspace": chat_id, "feedback": db.list_feedback()}

    @server.tool(
        description=(
            "Classify a piece of raw product input — a customer quote, a bug "
            "report, a request — into feature / bug / feedback with the fields "
            "Proxima would file it under. Returns the classification without "
            "writing it unless save=true."
        ),
        annotations=WRITES,
    )
    def triage(text: str, save: bool = False, workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        agent = pm.agent.ProximaAgent(database=db, system_prompt=pm.prompt.SYSTEM_PROMPT)
        intent = agent.understand_intent(text)

        result: dict[str, Any] = {"workspace": chat_id, "classification": intent, "saved": False}
        if not save:
            return result

        try:
            context.require_writable()
        except ResolutionError as exc:
            return {**result, "error": str(exc)}

        kind = intent.get("type")
        if kind == "Feature":
            row_id = db.create_feature(
                title=intent["title"],
                description=intent.get("description"),
                priority=intent.get("priority", "medium"),
                impact=intent.get("impact", "medium"),
                effort=intent.get("effort", "medium"),
            )
        elif kind == "Bug":
            row_id = db.create_bug(
                title=intent["title"],
                description=intent.get("description"),
                severity=intent.get("severity", "medium"),
            )
        elif kind == "Feedback":
            row_id = db.create_feedback(
                source=intent.get("source"),
                content=intent.get("content", text),
                sentiment=intent.get("sentiment", "neutral"),
            )
        else:
            # "Unknown" is a real answer — filing it somewhere anyway is how a
            # backlog fills up with rows nobody can act on.
            return {**result, "note": "Not classifiable; nothing written."}

        return {**result, "saved": True, "id": row_id, "table": kind.lower()}

    if not context.read_only:

        @server.tool(
            description="Add a feature to the product's feature list.",
            annotations=WRITES,
        )
        def add_feature(
            title: str,
            description: str = "",
            priority: str = "medium",
            impact: str = "medium",
            effort: str = "medium",
            status: str = "planned",
            workspace: str | None = None,
        ) -> dict[str, Any]:
            try:
                db, chat_id = store(workspace)
            except ResolutionError as exc:
                return _err(exc)
            row_id = db.create_feature(title, description, priority, impact, effort, status)
            return {"workspace": chat_id, "id": row_id, "title": title}

        @server.tool(description="File a bug.", annotations=WRITES)
        def add_bug(
            title: str,
            description: str = "",
            severity: str = "medium",
            status: str = "open",
            workspace: str | None = None,
        ) -> dict[str, Any]:
            try:
                db, chat_id = store(workspace)
            except ResolutionError as exc:
                return _err(exc)
            row_id = db.create_bug(title, description, severity, status)
            return {"workspace": chat_id, "id": row_id, "title": title}

        @server.tool(
            description="Record a piece of customer feedback verbatim.",
            annotations=WRITES,
        )
        def add_feedback(
            content: str,
            source: str = "",
            sentiment: str = "neutral",
            workspace: str | None = None,
        ) -> dict[str, Any]:
            try:
                db, chat_id = store(workspace)
            except ResolutionError as exc:
                return _err(exc)
            row_id = db.create_feedback(source or None, content, sentiment)
            return {"workspace": chat_id, "id": row_id}

    # ----------------------------------------------------------------- board

    @server.tool(
        description=(
            "Tickets on the board. Tickets are work; features are what the "
            "product does — they are separate on purpose. Pass sprint_id to "
            "scope to one sprint."
        ),
        annotations=READS,
    )
    def list_tickets(sprint_id: int | None = None, workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)
        return {"workspace": chat_id, "tickets": db.list_tickets(sprint_id)}

    @server.tool(description="Sprints defined in this workspace.", annotations=READS)
    def list_sprints(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)
        return {"workspace": chat_id, "sprints": db.list_sprints()}

    if not context.read_only:

        @server.tool(
            description=(
                "Create a ticket on the board. status is one of Backlog / "
                "In Progress / Review / Done; priority is Low / Medium / High."
            ),
            annotations=WRITES,
        )
        def add_ticket(
            title: str,
            description: str = "",
            status: str = "Backlog",
            priority: str = "Medium",
            estimate: int | None = None,
            sprint_id: int | None = None,
            feature_id: int | None = None,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            try:
                db, chat_id = store(workspace)
            except ResolutionError as exc:
                return _err(exc)
            row_id = db.create_ticket(
                title, description, status, priority, estimate, sprint_id,
                feature_id, origin="mcp",
            )
            return {"workspace": chat_id, "id": row_id, "title": title, "status": status}

        @server.tool(
            description=(
                "Change a ticket in place — most often its status, to move it "
                "across the board. Only the fields you pass are touched."
            ),
            annotations=UPDATES,
        )
        def update_ticket(
            ticket_id: int,
            title: str | None = None,
            description: str | None = None,
            status: str | None = None,
            priority: str | None = None,
            estimate: int | None = None,
            sprint_id: int | None = None,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            try:
                db, chat_id = store(workspace)
            except ResolutionError as exc:
                return _err(exc)

            fields = {
                key: value
                for key, value in {
                    "title": title, "description": description, "status": status,
                    "priority": priority, "estimate": estimate, "sprint_id": sprint_id,
                }.items()
                if value is not None
            }
            if not fields:
                return {"workspace": chat_id, "id": ticket_id, "changed": [],
                        "note": "No fields given; nothing changed."}

            db.update_ticket(ticket_id, **fields)
            after = [t for t in db.list_tickets() if t["id"] == ticket_id]
            return {
                "workspace": chat_id,
                "id": ticket_id,
                "changed": sorted(fields),
                "ticket": after[0] if after else None,
            }

    # ----------------------------------------------------------- competitors

    @server.tool(
        description=(
            "Competitors tracked in this workspace, with how many features are "
            "on file for each. A competitor with zero features cannot be "
            "scored — it reads as Unknown, not as an advantage."
        ),
        annotations=READS,
    )
    def list_competitors(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        features = db.list_competitor_features()
        counts: dict[str, int] = {}
        for feature in features:
            counts[feature["competitor_name"]] = counts.get(feature["competitor_name"], 0) + 1
        return {
            "workspace": chat_id,
            "competitors": [
                {**rival, "feature_count": counts.get(rival["name"], 0)}
                for rival in db.list_competitors()
            ],
        }

    @server.tool(
        description="Every competitor feature on file, with its competitor.",
        annotations=READS,
    )
    def list_competitor_features(
        competitor: str | None = None, workspace: str | None = None
    ) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        features = db.list_competitor_features()
        if competitor:
            wanted = competitor.strip().lower()
            features = [f for f in features if f["competitor_name"].lower() == wanted]
        return {"workspace": chat_id, "features": features}

    @server.tool(
        description=(
            "How you stand against each competitor: share of their surface you "
            "cover, features of theirs you have no answer for, and a Low / "
            "Moderate / High / Unknown threat read. Most threatening first."
        ),
        annotations=READS,
    )
    def competitive_position(
        competitors: list[str] | None = None, workspace: str | None = None
    ) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        analyzer = pm.competitors.CompetitorAnalyzer(db)
        scores = analyzer.score_competitors(competitor_names=competitors)
        return {
            "workspace": chat_id,
            "scores": [asdict(score) for score in scores],
            "note": (
                "overlap is the share of that competitor's features you also "
                "ship. 'Unknown' means no feature list is on file for them."
            ),
        }

    @server.tool(
        description=(
            "The coverage matrix: your features down the side, competitors "
            "across the top, each cell match / partial / gap with its "
            "similarity score."
        ),
        annotations=READS,
    )
    def coverage_matrix(
        competitors: list[str] | None = None, workspace: str | None = None
    ) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        analyzer = pm.competitors.CompetitorAnalyzer(db)
        rows = analyzer.build_matrix(competitor_names=competitors)
        return {
            "workspace": chat_id,
            "rows": [
                {
                    "feature": row.feature,
                    "description": row.description,
                    "coverage": row.coverage,
                    "is_differentiator": row.is_differentiator,
                    "per_competitor": row.per_competitor,
                }
                for row in rows
            ],
        }

    @server.tool(
        description=(
            "Gaps and differentiators. Gaps are labelled by pressure: 'Table "
            "stakes' (every rival ships it), 'Emerging' (more than one), "
            "'Single-vendor bet' (one). Differentiators are features no "
            "competitor has a strong equivalent for."
        ),
        annotations=READS,
    )
    def find_gaps(
        competitors: list[str] | None = None, workspace: str | None = None
    ) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        analyzer = pm.competitors.CompetitorAnalyzer(db)
        return {"workspace": chat_id, **analyzer.gap_analysis(competitor_names=competitors)}

    if not context.read_only:

        @server.tool(
            description=(
                "Add or update a competitor, optionally with the features they "
                "ship. Matching is by name, so calling this twice updates "
                "rather than duplicates. Only record features you have actually "
                "verified — an invented feature list produces a confident, "
                "wrong competitive read."
            ),
            annotations=UPDATES,
        )
        def save_competitor(
            name: str,
            website: str = "",
            positioning: str = "",
            pricing: str = "",
            notes: str = "",
            features: list[str] | None = None,
            workspace: str | None = None,
        ) -> dict[str, Any]:
            try:
                db, chat_id = store(workspace)
            except ResolutionError as exc:
                return _err(exc)

            rival_id = db.upsert_competitor(
                name, website or None, positioning or None, pricing or None, notes or None
            )

            added = 0
            if features:
                existing = {
                    f["name"].strip().lower()
                    for f in db.list_competitor_features(rival_id)
                }
                for feature in features:
                    label = (feature or "").strip()
                    if not label or label.lower() in existing:
                        continue
                    db.create_competitor_feature(rival_id, label, source_url=website or None)
                    existing.add(label.lower())
                    added += 1

            return {
                "workspace": chat_id,
                "competitor_id": rival_id,
                "name": name,
                "features_added": added,
            }

    # ---------------------------------------------------------- copyright/IP

    @server.tool(
        description=(
            "Check a feature you are about to build against the competitor "
            "material in this workspace. Scores concept, expression and name "
            "separately: copyright protects expression, not ideas, so a "
            "concept-identical feature with independent wording is the normal, "
            "low-risk case. Returns a 0-100 score, findings with evidence, and "
            "recommended actions. Not legal advice."
        ),
        annotations=WRITES,
    )
    def assess_ip_risk(
        feature_title: str,
        feature_description: str = "",
        top_n: int = 5,
        save: bool = False,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        analyzer = pm.copyright_analyzer.CopyrightAnalyzer(db)
        report = analyzer.analyze(feature_title, feature_description, top_n=top_n)

        payload = {
            "workspace": chat_id,
            "feature_title": report.feature_title,
            "risk_level": report.risk_level,
            "risk_score": report.risk_score,
            "matches": [
                {**asdict(match), "relationship": match.relationship}
                for match in report.matches
            ],
            "findings": [asdict(finding) for finding in report.findings],
            "recommendations": report.recommendations,
            "disclaimer": report.disclaimer,
            "saved": False,
        }

        if save and not context.read_only:
            assessment_id = db.create_ip_assessment(
                report.feature_title, report.feature_description,
                report.risk_level, report.risk_score, report.to_json(),
            )
            payload["saved"] = True
            payload["id"] = assessment_id
        elif save:
            payload["error"] = "Server is read-only; the assessment was not saved."

        return payload

    @server.tool(
        description=(
            "Run every feature in the workspace against every competitor at "
            "once, worst first. Answers 'which of the things we are building "
            "look like someone else's, and whose' — which the single-feature "
            "check cannot, because risk concentrated in one rival reads "
            "differently from the same score spread across five. Not legal advice."
        ),
        annotations=READS,
    )
    def sweep_ip_risk(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)

        analyzer = pm.copyright_analyzer.CopyrightAnalyzer(db)
        sweep = pm.copyright_analyzer.CopyrightSweep(analyzer)
        rows = sweep.run(db.list_features(), db.list_competitor_features())
        return {
            "workspace": chat_id,
            "rows": [
                {
                    "feature": row.feature_title,
                    "worst_score": row.worst_score,
                    "worst_level": row.worst_level,
                    "worst_competitor": row.worst_competitor,
                    "per_competitor": {
                        name: asdict(cell) for name, cell in row.per_competitor.items()
                    },
                }
                for row in rows
            ],
            "disclaimer": pm.copyright_analyzer.DISCLAIMER,
        }

    @server.tool(
        description="Past IP assessments saved in this workspace, newest first.",
        annotations=READS,
    )
    def list_ip_assessments(workspace: str | None = None) -> dict[str, Any]:
        try:
            db, chat_id = store(workspace)
        except ResolutionError as exc:
            return _err(exc)
        return {"workspace": chat_id, "assessments": db.list_ip_assessments()}

    _register_resources(server, context)
    _register_prompts(server)
    return server


# --------------------------------------------------------------- resources

def _register_resources(server: MCPServer, context: Context) -> None:
    """Read-only views a client can attach as context without calling a tool.

    Same data as the tools, different affordance: a resource is something the
    user pins to a conversation, a tool is something the model decides to run.
    """

    @server.resource(
        "proxima://workspaces",
        name="Proxima workspaces",
        description="Every chat workspace on this machine.",
        mime_type="application/json",
    )
    def workspaces_resource() -> str:
        import json

        return json.dumps(
            [
                {"id": w.id, "title": w.title, "created": w.created}
                for w in context.workspaces()
            ],
            indent=2,
        )

    @server.resource(
        "proxima://{workspace}/features",
        name="Product features",
        description="The feature list of one workspace.",
        mime_type="application/json",
    )
    def features_resource(workspace: str) -> str:
        import json

        db, _ = context.database(workspace)
        return json.dumps(db.list_features(), indent=2, default=str)

    @server.resource(
        "proxima://{workspace}/competitors",
        name="Competitors",
        description="Competitors and their features, for one workspace.",
        mime_type="application/json",
    )
    def competitors_resource(workspace: str) -> str:
        import json

        db, _ = context.database(workspace)
        return json.dumps(
            {
                "competitors": db.list_competitors(),
                "features": db.list_competitor_features(),
            },
            indent=2,
            default=str,
        )


# ----------------------------------------------------------------- prompts

def _register_prompts(server: MCPServer) -> None:
    """Canned openings for the two analyses people actually run."""

    @server.prompt(
        name="competitive_review",
        description="Ask for a prioritisation recommendation from the gap analysis.",
    )
    def competitive_review(workspace: str = "") -> str:
        scope = f" in workspace {workspace}" if workspace else ""
        return (
            f"Use the Proxima tools to read the competitive position{scope}: call "
            "competitive_position and find_gaps. Then recommend what to build "
            "next. Weigh table-stakes gaps against protecting the "
            "differentiators, say what you would *not* build, and name the "
            "competitor each recommendation is a response to. Treat any "
            "competitor marked Unknown as missing research, not as a win."
        )

    @server.prompt(
        name="ip_check",
        description="Check a feature for copyright/IP risk before building it.",
    )
    def ip_check(feature_title: str, feature_description: str = "") -> str:
        return (
            f"Run assess_ip_risk on the feature {feature_title!r}"
            + (f" — {feature_description}" if feature_description else "")
            + ". Then explain the result in plain language: separate the "
            "concept overlap (normal competition) from the expression overlap "
            "(the actual copyright signal), quote any verbatim evidence, and "
            "give me the concrete next action. Repeat the disclaimer: this is "
            "text similarity over the material in this workspace, not legal "
            "advice and not a trademark or patent search."
        )
