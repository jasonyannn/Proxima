# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Competitive analysis: compare our product's features against competitors'.

Produces three things the chat interface can't:

1. A coverage matrix  -- our feature x each competitor, with a match strength.
2. A gap analysis     -- what they ship that we don't (and vice versa).
3. A positioning read -- per-competitor parity/differentiation/threat scores.

Matching is by text similarity (see textsim), so it degrades gracefully: a
competitor feature called "Dark theme" still matches our "Dark mode".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from .textsim import concept_similarity, feature_similarity
except ImportError:  # pragma: no cover
    from textsim import concept_similarity, feature_similarity

# Calibrated against a labelled set of feature pairs (see tests/test_analysis.py).
# On that set, unrelated pairs score ~0.0 and same-job pairs score 0.37-1.0, so
# these sit in the empty band between the two clusters with headroom on each side.
MATCH_STRONG = 0.35
MATCH_PARTIAL = 0.18

STATUS_MATCH = "Match"
STATUS_PARTIAL = "Partial"
STATUS_GAP = "Gap"

# Distinct from Gap on purpose. A gap means we looked at their feature list and
# ours is not in it; unknown means there is no list to look at. Reporting the
# second as the first turns "we have not researched them" into "we are ahead",
# which is the most flattering possible lie a competitive tool can tell.
STATUS_UNKNOWN = "Unknown"


def _label_of(feature: dict[str, Any]) -> str:
    return feature.get("title") or feature.get("name") or "Untitled"


def classify(score: float) -> str:
    if score >= MATCH_STRONG:
        return STATUS_MATCH
    if score >= MATCH_PARTIAL:
        return STATUS_PARTIAL
    return STATUS_GAP


@dataclass
class FeatureComparison:
    """One row of the matrix: our feature, scored against every competitor."""

    feature: str
    description: str = ""
    # competitor name -> {status, score, matched_feature}
    per_competitor: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def is_differentiator(self) -> bool:
        """No competitor has a strong match for this."""
        return all(
            cell["status"] != STATUS_MATCH for cell in self.per_competitor.values()
        ) and bool(self.per_competitor)

    @property
    def coverage(self) -> float:
        """Fraction of competitors that also ship this."""
        if not self.per_competitor:
            return 0.0
        matched = sum(
            1 for cell in self.per_competitor.values() if cell["status"] == STATUS_MATCH
        )
        return round(matched / len(self.per_competitor), 4)


@dataclass
class CompetitorScore:
    name: str
    overlap: float          # share of their features we also cover
    parity_count: int       # features both of us have
    their_advantage: list[dict[str, Any]]  # they have, we don't
    our_advantage: list[str]               # we have, they don't
    threat: str             # Low / Moderate / High
    researched: bool = True  # False when we hold no feature list for them


class CompetitorAnalyzer:
    def __init__(self, database: Any) -> None:
        self.database = database

    # --- data access -----------------------------------------------------

    def our_features(self) -> list[dict[str, Any]]:
        return self.database.list_features()

    def competitors(self) -> list[dict[str, Any]]:
        return self.database.list_competitors()

    def competitor_features(self) -> list[dict[str, Any]]:
        return self.database.list_competitor_features()

    # --- core analysis ---------------------------------------------------

    def best_match(
        self, feature: dict[str, Any], candidates: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, float]:
        """Highest-scoring candidate for `feature`, with its score."""
        title, description = _label_of(feature), feature.get("description") or ""
        best: dict[str, Any] | None = None
        best_score = 0.0
        for candidate in candidates:
            score = feature_similarity(
                title,
                description,
                _label_of(candidate),
                candidate.get("description") or "",
            )
            if score > best_score:
                best, best_score = candidate, score
        return best, round(best_score, 4)

    def build_matrix(
        self,
        our_features: list[dict[str, Any]] | None = None,
        competitor_names: list[str] | None = None,
    ) -> list[FeatureComparison]:
        """One FeatureComparison per feature of ours, scored against each rival."""
        ours = our_features if our_features is not None else self.our_features()
        all_rival_features = self.competitor_features()

        names = competitor_names
        if names is None:
            names = [c["name"] for c in self.competitors()]

        by_competitor: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
        for feature in all_rival_features:
            if feature["competitor_name"] in by_competitor:
                by_competitor[feature["competitor_name"]].append(feature)

        matrix: list[FeatureComparison] = []
        for feature in ours:
            row = FeatureComparison(
                feature=_label_of(feature),
                description=feature.get("description") or "",
            )
            for name in names:
                if not by_competitor[name]:
                    row.per_competitor[name] = {
                        "status": STATUS_UNKNOWN,
                        "score": 0.0,
                        "matched_feature": None,
                    }
                    continue
                match, score = self.best_match(feature, by_competitor[name])
                row.per_competitor[name] = {
                    "status": classify(score),
                    "score": score,
                    "matched_feature": _label_of(match) if match else None,
                }
            matrix.append(row)
        return matrix

    def score_competitors(
        self,
        our_features: list[dict[str, Any]] | None = None,
        competitor_names: list[str] | None = None,
    ) -> list[CompetitorScore]:
        """Per-competitor positioning summary, most threatening first."""
        ours = our_features if our_features is not None else self.our_features()
        names = competitor_names
        if names is None:
            names = [c["name"] for c in self.competitors()]

        all_rival_features = self.competitor_features()
        matrix = self.build_matrix(ours, names)

        scores: list[CompetitorScore] = []
        for name in names:
            theirs = [f for f in all_rival_features if f["competitor_name"] == name]

            # What they ship that we have no answer for.
            their_advantage = []
            for rival_feature in theirs:
                _, score = self.best_match(rival_feature, ours)
                if classify(score) != STATUS_MATCH:
                    their_advantage.append(
                        {
                            "feature": _label_of(rival_feature),
                            "description": rival_feature.get("description") or "",
                            "closeness": score,
                        }
                    )

            # With nothing on file for them, we know nothing — not that we are
            # ahead. Every number below would otherwise read as a clean sweep.
            if not theirs:
                scores.append(
                    CompetitorScore(
                        name=name,
                        overlap=0.0,
                        parity_count=0,
                        their_advantage=[],
                        our_advantage=[],
                        threat="Unknown",
                        researched=False,
                    )
                )
                continue

            our_advantage = [
                row.feature
                for row in matrix
                if row.per_competitor.get(name, {}).get("status") != STATUS_MATCH
            ]
            parity_count = len(theirs) - len(their_advantage)
            overlap = round(parity_count / len(theirs), 4) if theirs else 0.0

            # Threat rises with how much of our surface they cover *and* how
            # much of theirs we cannot answer.
            unanswered = len(their_advantage)
            if overlap >= 0.6 and unanswered >= 3:
                threat = "High"
            elif overlap >= 0.35 or unanswered >= 3:
                threat = "Moderate"
            else:
                threat = "Low"

            scores.append(
                CompetitorScore(
                    name=name,
                    overlap=overlap,
                    parity_count=parity_count,
                    their_advantage=sorted(
                        their_advantage, key=lambda item: item["closeness"]
                    ),
                    our_advantage=our_advantage,
                    threat=threat,
                )
            )

        # Unknown sorts last: it is not a verdict, it is missing homework.
        rank = {"High": 0, "Moderate": 1, "Low": 2, "Unknown": 3}
        return sorted(scores, key=lambda s: (rank[s.threat], -s.overlap))

    def gap_analysis(
        self,
        our_features: list[dict[str, Any]] | None = None,
        competitor_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Table-stakes gaps, differentiators, and parity features."""
        ours = our_features if our_features is not None else self.our_features()
        names = competitor_names
        if names is None:
            names = [c["name"] for c in self.competitors()]

        matrix = self.build_matrix(ours, names)
        all_rival_features = [
            f for f in self.competitor_features() if f["competitor_name"] in names
        ]

        # Cluster rival features we don't answer, so "Dark theme" from three
        # competitors reports as one gap with three sources rather than three gaps.
        missing: list[dict[str, Any]] = []
        for rival_feature in all_rival_features:
            _, score = self.best_match(rival_feature, ours)
            if classify(score) == STATUS_MATCH:
                continue
            label = _label_of(rival_feature)
            for existing in missing:
                if concept_similarity(label, existing["feature"]) >= MATCH_STRONG:
                    existing["competitors"].append(rival_feature["competitor_name"])
                    break
            else:
                missing.append(
                    {
                        "feature": label,
                        "description": rival_feature.get("description") or "",
                        "competitors": [rival_feature["competitor_name"]],
                        "closeness": score,
                    }
                )

        for gap in missing:
            gap["competitors"] = sorted(set(gap["competitors"]))
            # Something every rival ships is table stakes; one rival = a bet.
            shipped_by = len(gap["competitors"])
            if names and shipped_by >= max(2, len(names)):
                gap["pressure"] = "Table stakes"
            elif shipped_by > 1:
                gap["pressure"] = "Emerging"
            else:
                gap["pressure"] = "Single-vendor bet"

        pressure_rank = {"Table stakes": 0, "Emerging": 1, "Single-vendor bet": 2}
        missing.sort(key=lambda g: (pressure_rank[g["pressure"]], -len(g["competitors"])))

        return {
            "we_are_missing": missing,
            "our_differentiators": [
                {"feature": row.feature, "description": row.description}
                for row in matrix
                if row.is_differentiator
            ],
            "parity": [
                {"feature": row.feature, "coverage": row.coverage}
                for row in matrix
                if not row.is_differentiator
            ],
        }

    # --- narrative -------------------------------------------------------

    def summary_prompt(self, gaps: dict[str, Any], scores: list[CompetitorScore]) -> str:
        """Compact briefing for the LLM to turn into a strategic recommendation."""
        lines = ["Competitive position:", ""]
        for score in scores:
            lines.append(
                f"- {score.name}: threat {score.threat}, "
                f"{int(score.overlap * 100)}% of their surface matched by us, "
                f"{len(score.their_advantage)} features we don't answer."
            )
        lines.append("")
        lines.append("Gaps (features rivals have, we don't):")
        for gap in gaps["we_are_missing"][:10]:
            lines.append(
                f"- {gap['feature']} [{gap['pressure']}] "
                f"shipped by: {', '.join(gap['competitors'])}"
            )
        lines.append("")
        lines.append("Our differentiators:")
        for item in gaps["our_differentiators"][:10]:
            lines.append(f"- {item['feature']}")
        return "\n".join(lines)
