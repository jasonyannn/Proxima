"""Illustrative starter data so the analysers have something to chew on.

These entries are generic placeholders written for demo purposes, not researched
claims about any real company's shipping feature set. Replace them with your own
verified competitor research before you rely on any output.
"""

from __future__ import annotations

from typing import Any

SAMPLE_COMPETITORS: list[dict[str, Any]] = [
    {
        "name": "Northwind PM",
        "website": "https://example.com/northwind",
        "positioning": "Enterprise roadmapping suite for large product orgs.",
        "pricing": "$45/user/mo, annual contract",
        "notes": "Sample data — replace with your own research.",
        "features": [
            {
                "name": "Roadmap timeline",
                "category": "Planning",
                "description": "Drag-and-drop timeline view showing initiatives across quarters with dependency lines.",
            },
            {
                "name": "Idea portal",
                "category": "Feedback",
                "description": "Public portal where customers submit ideas and vote on existing submissions.",
            },
            {
                "name": "Impact scoring",
                "category": "Prioritisation",
                "description": "Weighted scoring model that ranks backlog items by reach, impact, confidence and effort.",
            },
            {
                "name": "Executive dashboards",
                "category": "Reporting",
                "description": "Rolled-up progress dashboards aimed at leadership reporting cycles.",
            },
            {
                "name": "SSO and audit log",
                "category": "Enterprise",
                "description": "SAML single sign-on plus an immutable audit trail of workspace changes.",
            },
        ],
    },
    {
        "name": "Cobalt Board",
        "website": "https://example.com/cobalt",
        "positioning": "Fast issue tracker favoured by engineering-led teams.",
        "pricing": "$12/user/mo",
        "notes": "Sample data — replace with your own research.",
        "features": [
            {
                "name": "Keyboard-first navigation",
                "category": "UX",
                "description": "Every action reachable via a command palette and keyboard shortcuts.",
            },
            {
                "name": "Sprint cycles",
                "category": "Planning",
                "description": "Automatic two-week cycles that roll unfinished work forward.",
            },
            {
                "name": "Git integration",
                "category": "Engineering",
                "description": "Links branches and pull requests to issues and moves status automatically.",
            },
            {
                "name": "Dark mode",
                "category": "UX",
                "description": "System-aware dark colour theme across the whole application.",
            },
            {
                "name": "Triage inbox",
                "category": "Workflow",
                "description": "Queue where incoming bug reports are reviewed and routed to an owner.",
            },
        ],
    },
    {
        "name": "Vellum Insights",
        "website": "https://example.com/vellum",
        "positioning": "Customer feedback aggregation and analysis.",
        "pricing": "$29/user/mo",
        "notes": "Sample data — replace with your own research.",
        "features": [
            {
                "name": "Feedback inbox",
                "category": "Feedback",
                "description": "Collects customer messages from support tools, sales calls and surveys into one queue.",
            },
            {
                "name": "Sentiment analysis",
                "category": "AI",
                "description": "Classifies each piece of feedback as positive, neutral or negative and trends it over time.",
            },
            {
                "name": "Theme clustering",
                "category": "AI",
                "description": "Groups related feedback into recurring themes so demand signals are visible without manual tagging.",
            },
            {
                "name": "AI summary digest",
                "category": "AI",
                "description": "Weekly generated summary of what customers asked for and what changed.",
            },
            {
                "name": "Competitor mention tracking",
                "category": "Market",
                "description": "Flags feedback where a customer names a competing product.",
            },
        ],
    },
]


def seed(database: Any, *, include_our_features: bool = True) -> dict[str, int]:
    """Load the sample catalogue. Idempotent on competitors, by name."""
    database.init_db()
    counts = {"competitors": 0, "competitor_features": 0, "our_features": 0}

    existing_features = {
        (f["competitor_name"], f["name"]) for f in database.list_competitor_features()
    }

    for entry in SAMPLE_COMPETITORS:
        competitor_id = database.upsert_competitor(
            name=entry["name"],
            website=entry.get("website"),
            positioning=entry.get("positioning"),
            pricing=entry.get("pricing"),
            notes=entry.get("notes"),
        )
        counts["competitors"] += 1
        for feature in entry["features"]:
            if (entry["name"], feature["name"]) in existing_features:
                continue
            database.create_competitor_feature(
                competitor_id=competitor_id,
                name=feature["name"],
                description=feature.get("description"),
                category=feature.get("category"),
                source_url=entry.get("website"),
            )
            counts["competitor_features"] += 1

    if include_our_features and not database.list_features():
        for title, description in [
            (
                "Conversational backlog capture",
                "Product manager describes customer feedback in plain language and the agent files it as a structured feature, bug or feedback record.",
            ),
            (
                "Automatic intent classification",
                "Incoming text is classified as a feature request, bug report or general feedback without manual tagging.",
            ),
            (
                "Local-first LLM",
                "Runs against a locally hosted model so customer feedback never leaves the machine.",
            ),
            (
                "Sentiment inference",
                "Infers whether feedback is positive, neutral or negative and stores it with the record.",
            ),
        ]:
            database.create_feature(
                title=title,
                description=description,
                priority="medium",
                impact="medium",
                effort="medium",
                status="shipped",
            )
            counts["our_features"] += 1

    return counts


# Names of everything this module creates, so the UI can tell demo rows apart
# from real research the user entered themselves and say so plainly.
SAMPLE_COMPETITOR_NAMES = frozenset(entry["name"] for entry in SAMPLE_COMPETITORS)


def loaded_samples(database: Any) -> list[dict[str, Any]]:
    """Which sample competitors are currently in the workspace."""
    return [
        competitor
        for competitor in database.list_competitors()
        if competitor["name"] in SAMPLE_COMPETITOR_NAMES
    ]


def clear_samples(database: Any) -> int:
    """Remove the sample competitors and their features. Returns how many went.

    Only touches rows this module created — anything the user added by hand
    stays put, including a real competitor that happens to sit alongside them.
    """
    removed = 0
    for competitor in loaded_samples(database):
        database.delete_competitor(competitor["id"])
        removed += 1
    return removed
