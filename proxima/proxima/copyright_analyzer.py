"""Copyright / IP risk analyser for a proposed feature.

WHAT THIS IS
    A triage tool. It compares a feature you're about to build against the
    competitor features in your catalogue and tells you which parts look like
    independent design and which parts look copied.

WHAT THIS IS NOT
    Legal advice, and not a patent or trademark search. It only sees the text
    you have loaded locally. Treat a high score as "route this past counsel",
    never as a verdict. See DISCLAIMER below -- the UI surfaces it verbatim.

THE MODEL
    Copyright protects *expression*, not *ideas*. Building a dark mode because
    a rival has one is normal competition; shipping their help-centre copy
    word-for-word is not. So the analyser scores three axes independently
    instead of emitting one meaningless "similarity" number:

      concept    high -> you're in the same market. Not a copyright problem
                         on its own; may be a patent question for novel methods.
      expression high -> the *wording* tracks theirs. This is the copyright
                         signal, and it dominates the risk score.
      name       high -> confusable branding. A trademark question, not copyright.

    A feature that is concept-identical but expression-distinct is the normal,
    low-risk case, and the report says so explicitly rather than alarming you.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from typing import Any

try:
    from .textsim import (
        feature_similarity,
        expression_similarity,
        name_similarity,
        shared_phrases,
        longest_common_phrase,
    )
except ImportError:  # pragma: no cover
    from textsim import (
        feature_similarity,
        expression_similarity,
        name_similarity,
        shared_phrases,
        longest_common_phrase,
    )

DISCLAIMER = (
    "This is an automated triage signal based only on the competitor text stored "
    "in this workspace. It is not legal advice, and it is not a patent, trademark "
    "or registered-copyright search. Have qualified counsel review anything "
    "flagged Elevated or High before you ship."
)

# Thresholds. Expression is held to a higher bar than concept because
# incidental wording overlap between two feature descriptions is common.
EXPRESSION_HIGH = 0.72
EXPRESSION_MODERATE = 0.50
# Aligned with competitors.MATCH_STRONG: on the labelled calibration set,
# same-job feature pairs score >= 0.35 and unrelated pairs score ~0.0.
CONCEPT_HIGH = 0.35
NAME_HIGH = 0.80
VERBATIM_PHRASE_WORDS = 6

# Phrases in a spec that signal intent to reproduce rather than to compete.
_COPY_INTENT = re.compile(
    r"\b(clone|copy|replicate|rip off|identical to|exactly like|same as|"
    r"pixel[- ]perfect|1:1|mirror|port(?:ed)? (?:from|of)|reverse[- ]engineer)\b",
    re.IGNORECASE,
)

# Asset classes where copying is a real, direct copyright exposure.
_PROTECTED_ASSETS = re.compile(
    r"\b(icon set|icons|illustration|artwork|logo|font|typeface|screenshot|"
    r"source code|code ?base|snippet|sdk|stylesheet|css|template|copy ?text|"
    r"marketing copy|documentation|help ?(?:centre|center) ?(?:article|content)|"
    r"dataset|training data|sound|audio|video)\b",
    re.IGNORECASE,
)


@dataclass
class Finding:
    """One piece of evidence behind the score."""

    kind: str          # copyright | trademark | patent | practice
    severity: str      # Info | Low | Moderate | High
    competitor: str | None
    feature: str | None
    detail: str
    evidence: str = ""


@dataclass
class Match:
    competitor: str
    feature: str
    description: str
    concept: float
    expression: float
    name: float
    verbatim: str = ""

    @property
    def relationship(self) -> str:
        """Plain-language read of how this feature relates to ours."""
        if self.expression >= EXPRESSION_HIGH:
            return "Near-verbatim wording"
        if self.concept >= CONCEPT_HIGH and self.expression < EXPRESSION_MODERATE:
            return "Same idea, independent expression"
        if self.concept >= CONCEPT_HIGH:
            return "Same idea, overlapping wording"
        return "Loosely related"


@dataclass
class IPReport:
    feature_title: str
    feature_description: str
    risk_level: str            # Low | Moderate | Elevated | High
    risk_score: float          # 0-100
    matches: list[Match] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def to_json(self) -> str:
        payload = asdict(self)
        payload["matches"] = [
            {**asdict(m), "relationship": m.relationship} for m in self.matches
        ]
        return json.dumps(payload, indent=2)


class CopyrightAnalyzer:
    def __init__(self, database: Any = None) -> None:
        self.database = database

    def analyze(
        self,
        feature_title: str,
        feature_description: str = "",
        competitor_features: list[dict[str, Any]] | None = None,
        top_n: int = 5,
    ) -> IPReport:
        if competitor_features is None:
            competitor_features = (
                self.database.list_competitor_features() if self.database else []
            )

        our_text = f"{feature_title}. {feature_description}".strip()
        matches = self._score_matches(
            feature_title, feature_description, our_text, competitor_features
        )
        top_matches = matches[:top_n]

        findings = self._collect_findings(
            feature_title, feature_description, our_text, matches
        )
        score = self._score(matches, findings)
        level = self._level(score)
        recommendations = self._recommend(level, findings, matches)

        return IPReport(
            feature_title=feature_title,
            feature_description=feature_description,
            risk_level=level,
            risk_score=score,
            matches=top_matches,
            findings=findings,
            recommendations=recommendations,
        )

    # --- scoring ---------------------------------------------------------

    def _score_matches(
        self,
        title: str,
        our_description: str,
        our_text: str,
        competitor_features: list[dict[str, Any]],
    ) -> list[Match]:
        matches: list[Match] = []
        for rival in competitor_features:
            rival_name = rival.get("name") or ""
            rival_text = f"{rival_name}. {rival.get('description') or ''}".strip()

            concept = feature_similarity(
                title, our_description, rival_name, rival.get("description") or ""
            )
            expression = expression_similarity(our_text, rival_text)
            name = name_similarity(title, rival_name)

            # Ignore pairs with no meaningful relationship at all.
            if max(concept, expression, name) < 0.20:
                continue

            phrase = longest_common_phrase(our_text, rival_text)
            matches.append(
                Match(
                    competitor=rival.get("competitor_name") or "Unknown",
                    feature=rival_name,
                    description=rival.get("description") or "",
                    concept=concept,
                    expression=expression,
                    name=name,
                    verbatim=phrase if len(phrase.split()) >= 4 else "",
                )
            )

        # Rank by the axis that actually drives legal risk.
        matches.sort(key=lambda m: (-m.expression, -m.concept, -m.name))
        return matches

    def _collect_findings(
        self,
        title: str,
        description: str,
        our_text: str,
        matches: list[Match],
    ) -> list[Finding]:
        findings: list[Finding] = []

        for match in matches:
            if match.expression >= EXPRESSION_HIGH:
                findings.append(
                    Finding(
                        kind="copyright",
                        severity="High",
                        competitor=match.competitor,
                        feature=match.feature,
                        detail=(
                            f"Description wording is {int(match.expression * 100)}% similar to "
                            f"{match.competitor}'s '{match.feature}'. Copyright protects "
                            "expression, so near-verbatim text is the main exposure here."
                        ),
                        evidence=match.verbatim,
                    )
                )
            elif match.expression >= EXPRESSION_MODERATE:
                findings.append(
                    Finding(
                        kind="copyright",
                        severity="Moderate",
                        competitor=match.competitor,
                        feature=match.feature,
                        detail=(
                            f"Wording overlaps {int(match.expression * 100)}% with "
                            f"{match.competitor}'s '{match.feature}'. Likely shared domain "
                            "vocabulary, but rewrite in your own voice before publishing."
                        ),
                        evidence=match.verbatim,
                    )
                )

            phrases = [
                phrase
                for phrase in shared_phrases(
                    our_text, f"{match.feature}. {match.description}"
                )
                if len(phrase.split()) >= VERBATIM_PHRASE_WORDS
            ]
            if phrases:
                findings.append(
                    Finding(
                        kind="copyright",
                        severity="High",
                        competitor=match.competitor,
                        feature=match.feature,
                        detail=(
                            f"Shares a {len(phrases[0].split())}-word verbatim run with "
                            f"{match.competitor}'s material."
                        ),
                        evidence=phrases[0],
                    )
                )

            if match.name >= NAME_HIGH:
                findings.append(
                    Finding(
                        kind="trademark",
                        severity="Moderate",
                        competitor=match.competitor,
                        feature=match.feature,
                        detail=(
                            f"Feature name is confusably close to {match.competitor}'s "
                            f"'{match.feature}'. This is a trademark question, not copyright "
                            "— check whether the name is registered in your market."
                        ),
                        evidence=f"{title} vs {match.feature}",
                    )
                )

            if match.concept >= CONCEPT_HIGH and match.expression < EXPRESSION_MODERATE:
                findings.append(
                    Finding(
                        kind="patent",
                        severity="Low",
                        competitor=match.competitor,
                        feature=match.feature,
                        detail=(
                            f"Same functional idea as {match.competitor}'s '{match.feature}' "
                            "but independently worded. Copyright does not protect ideas, so "
                            "this is normal competition; only a granted patent on the specific "
                            "method would change that."
                        ),
                    )
                )

        if _COPY_INTENT.search(our_text):
            findings.append(
                Finding(
                    kind="practice",
                    severity="High",
                    competitor=None,
                    feature=None,
                    detail=(
                        "The spec describes reproducing another product rather than "
                        "competing with it. Intent language like this is damaging evidence "
                        "if a dispute ever arises — restate the requirement as an outcome."
                    ),
                    evidence=_first_match(_COPY_INTENT, our_text),
                )
            )

        assets = sorted({m.lower() for m in _PROTECTED_ASSETS.findall(our_text)})
        if assets:
            findings.append(
                Finding(
                    kind="copyright",
                    severity="Moderate",
                    competitor=None,
                    feature=None,
                    detail=(
                        "Mentions asset types that are directly copyrightable ("
                        + ", ".join(assets)
                        + "). Confirm each is original, licensed, or covered by its "
                        "open-source licence terms."
                    ),
                )
            )

        if not findings:
            findings.append(
                Finding(
                    kind="practice",
                    severity="Info",
                    competitor=None,
                    feature=None,
                    detail=(
                        "No meaningful overlap with the competitor material in this "
                        "workspace. Note this only covers what you have loaded."
                    ),
                )
            )

        severity_rank = {"High": 0, "Moderate": 1, "Low": 2, "Info": 3}
        findings.sort(key=lambda f: severity_rank[f.severity])
        return findings

    def _score(self, matches: list[Match], findings: list[Finding]) -> float:
        """0-100. Expression overlap dominates; concept overlap barely counts."""
        if not matches:
            return 0.0

        top_expression = max(m.expression for m in matches)
        top_concept = max(m.concept for m in matches)
        top_name = max(m.name for m in matches)

        score = (
            top_expression * 65      # the actual copyright signal
            + top_concept * 10       # same market, largely lawful
            + top_name * 15          # trademark confusion
        )

        # Verbatim runs and stated copy-intent are categorical, not gradual.
        if any(f.severity == "High" and f.kind == "copyright" for f in findings):
            score += 15
        if any(f.kind == "practice" and f.severity == "High" for f in findings):
            score += 20

        return round(min(score, 100.0), 1)

    def _level(self, score: float) -> str:
        if score >= 70:
            return "High"
        if score >= 45:
            return "Elevated"
        if score >= 22:
            return "Moderate"
        return "Low"

    def _recommend(
        self, level: str, findings: list[Finding], matches: list[Match]
    ) -> list[str]:
        recommendations: list[str] = []
        kinds = {f.kind for f in findings if f.severity in ("High", "Moderate")}

        if "copyright" in kinds:
            recommendations.append(
                "Rewrite the feature description and any user-facing copy from scratch, "
                "working from your own user research rather than a competitor's page."
            )
            recommendations.append(
                "Record who wrote the spec and what sources they used — a clean-room "
                "paper trail is the strongest defence against a copying claim."
            )
        if "trademark" in kinds:
            recommendations.append(
                "Rename the feature, then run a trademark search in every market you "
                "ship to before the name reaches marketing material."
            )
        if "patent" in {f.kind for f in findings}:
            recommendations.append(
                "The underlying idea is fair to build. If the implementation method is "
                "unusual, ask counsel for a freedom-to-operate check on that method only."
            )
        if any(f.kind == "practice" and f.severity == "High" for f in findings):
            recommendations.append(
                "Rephrase the requirement as the user outcome you want, not as a "
                "reference to reproducing another product."
            )

        if level in ("Elevated", "High"):
            recommendations.insert(
                0, "Hold this out of the sprint until counsel has reviewed it."
            )
        elif level == "Low":
            recommendations.append(
                "Safe to proceed on the evidence available. Re-run this if the scope "
                "changes or you add competitor material."
            )

        return recommendations

    # --- narrative -------------------------------------------------------

    def briefing(self, report: IPReport) -> str:
        """Compact briefing the LLM can turn into prose."""
        lines = [
            f"Proposed feature: {report.feature_title}",
            f"Description: {report.feature_description or '(none given)'}",
            f"Automated risk: {report.risk_level} ({report.risk_score}/100)",
            "",
            "Closest competitor features:",
        ]
        for match in report.matches:
            lines.append(
                f"- {match.competitor} / {match.feature}: {match.relationship} "
                f"(concept {int(match.concept * 100)}%, wording {int(match.expression * 100)}%)"
            )
        lines.append("")
        lines.append("Findings:")
        for finding in report.findings:
            lines.append(f"- [{finding.severity}/{finding.kind}] {finding.detail}")
        return "\n".join(lines)


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    found = pattern.search(text)
    return found.group(0) if found else ""
