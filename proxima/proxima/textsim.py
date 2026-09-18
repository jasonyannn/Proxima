# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Lightweight text-similarity helpers shared by the competitor and IP analysers.

Deliberately dependency-free: no numpy, no embeddings, no network. The signals
here are coarse but explainable, which matters because both callers show their
working to the user.

Three different notions of "similar" are kept separate on purpose:

- concept   : do two features do the same job? (token overlap, stemmed)
- expression: is the *wording* the same? (character n-grams + shared phrases)
- name      : are the product/feature names confusable? (edit distance + tokens)

That split is what lets the copyright analyser say "same idea, different
expression" -- which is the normal, low-risk case -- instead of collapsing
everything into one meaningless percentage.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Words that carry no signal when matching product features. Kept small and
# domain-specific rather than importing a full stopword corpus.
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "is", "are", "was", "were", "be", "been", "being", "to",
    "of", "in", "on", "at", "by", "for", "with", "without", "from", "into",
    "your", "our", "their", "its", "it", "you", "we", "they", "can", "will",
    "would", "should", "could", "may", "might", "must", "do", "does", "did",
    "have", "has", "had", "as", "so", "such", "via", "per", "up", "out", "over",
    "also", "any", "all", "each", "more", "most", "other", "some", "own", "new",
    "user", "users", "customer", "customers", "feature", "features", "product",
    "allow", "allows", "lets", "let", "able", "ability", "support", "supports",
    # Marketing modifiers. Every vendor prefixes the same capability with a
    # different adjective ("AI summary" / "smart summary" / "automatic
    # summary"), so these carry no signal about what the feature actually does.
    "ai", "artificial", "intelligence", "intelligent", "smart", "automatic",
    "automatically", "automated", "powered", "advanced", "seamless", "easy",
    "simple", "native", "built", "in", "based", "one", "click", "instantly",
}

# Suffix stripping. Not a real stemmer -- just enough to collapse the plural and
# gerund forms that make "exports report" and "report exporting" look unrelated.
# Ordered longest-first so "ization" is tried before "ation" before "ion".
_SUFFIXES = ("ization", "isation", "ations", "ation", "ingly", "edly", "ings",
             "ence", "ance", "ment", "ing", "ers", "ies", "ied", "er", "es",
             "ed", "ly", "s")

# Product-domain synonym families. Different vendors name the same job
# differently ("dark mode" vs "dark theme"), and no amount of stemming closes
# that gap -- only a vocabulary map does. Deliberately small: each entry is a
# pair we actually saw collide in real feature catalogues, not a thesaurus.
#
# Erring toward *fewer* entries is deliberate. A false match hides a real
# competitive gap, which costs more than a missed match. An earlier version
# mapped roadmap/timeline/sprint/backlog all to "plan"; that collapsed the
# two-word title "Roadmap timeline" to the single stem {plan}, which then
# matched anything else containing it at overlap 1.0.
_SYNONYMS = {
    # appearance
    "mode": "theme", "themes": "theme", "skin": "theme", "appearance": "theme",
    # sentiment family. "sentiment" maps to itself to stop the "ment" suffix
    # rule turning it into "senti".
    "sentiment": "sentiment", "sentiments": "sentiment", "mood": "sentiment",
    "emotion": "sentiment", "tone": "sentiment", "satisfaction": "sentiment",
    "happiness": "sentiment",
    # analysis. Only true synonyms: "scoring", "classification" and "detection"
    # were mapped here too, which wrongly matched "Impact scoring" against
    # "Sentiment inference" -- ranking and classifying are different jobs.
    "inference": "analysis", "infer": "analysis", "analyse": "analysis",
    "analyz": "analysis", "analysi": "analysis", "analytic": "analysis",
    # collection surfaces. "portal", "capture", "collect" and "triage" were
    # here too and over-merged: capturing input is not the same as a queue.
    "inbox": "queue", "intake": "queue",
    # grouping
    "cluster": "group", "grouping": "group", "tagging": "group",
    "categoris": "group", "categoriz": "group",
    # reporting. "dashboard" stays distinct -- it is a specific artefact, not a
    # synonym for any generated summary.
    "reporting": "report", "digest": "report", "summary": "report",
    "summaris": "report", "summariz": "report",
    # prioritisation
    "prioritis": "priority", "prioritiz": "priority", "priorit": "priority",
}


# Acronyms vendors use interchangeably with their expansion. Applied before
# stemming, because "SSO" and "single sign-on" share no characters at all and
# no similarity metric can bridge that on its own.
_ACRONYMS = {
    "sso": "single sign on",
    "mfa": "multi factor authentication",
    "2fa": "multi factor authentication",
    "rbac": "role based access control",
    "api": "application programming interface",
    "llm": "large language model",
    "nps": "net promoter score",
    "crm": "customer relationship management",
    "sla": "service level agreement",
    "ui": "user interface",
    "ux": "user experience",
    "pr": "pull request",
    "saml": "single sign on",
    "oidc": "single sign on",
}


def _expand_acronyms(words: list[str]) -> list[str]:
    expanded: list[str] = []
    for word in words:
        if word in _ACRONYMS:
            expanded.extend(_ACRONYMS[word].split())
        else:
            expanded.append(word)
    return expanded


def _stem(word: str) -> str:
    # Check the raw word first. Suffix stripping would otherwise mangle words
    # we care about ("sentiment" -> "senti") before the synonym map ever sees
    # them, so an entry mapping to itself also acts as a do-not-stem guard.
    if word in _SYNONYMS:
        return _SYNONYMS[word]
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            base = word[: -len(suffix)]
            # "ies"/"ied" -> "y" (categories -> category)
            if suffix in ("ies", "ied"):
                base = base + "y"
            return _SYNONYMS.get(base, base)
    return word


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str, *, keep_stopwords: bool = False) -> list[str]:
    words = _expand_acronyms(normalize(text).split())
    if not keep_stopwords:
        words = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return words


def stems(text: str) -> set[str]:
    return {_stem(w) for w in tokens(text)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    """Fraction of the *smaller* set that is shared.

    Better than Jaccard when a short feature name is compared against a long
    marketing description -- Jaccard would be punished by the length gap alone.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def char_ngrams(text: str, n: int = 4) -> set[str]:
    flat = normalize(text).replace(" ", "")
    if len(flat) < n:
        return {flat} if flat else set()
    return {flat[i : i + n] for i in range(len(flat) - n + 1)}


def dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def longest_common_phrase(a: str, b: str) -> str:
    """Longest run of consecutive shared words (the verbatim-copying signal)."""
    a_words = normalize(a).split()
    b_words = normalize(b).split()
    if not a_words or not b_words:
        return ""
    matcher = SequenceMatcher(None, a_words, b_words, autojunk=False)
    match = matcher.find_longest_match(0, len(a_words), 0, len(b_words))
    if match.size == 0:
        return ""
    return " ".join(a_words[match.a : match.a + match.size])


def shared_phrases(a: str, b: str, min_words: int = 3) -> list[str]:
    """All shared word-runs of at least `min_words`, longest first."""
    a_words = normalize(a).split()
    b_words = normalize(b).split()
    if not a_words or not b_words:
        return []
    matcher = SequenceMatcher(None, a_words, b_words, autojunk=False)
    found = [
        " ".join(a_words[block.a : block.a + block.size])
        for block in matcher.get_matching_blocks()
        if block.size >= min_words
    ]
    return sorted(set(found), key=lambda phrase: -len(phrase.split()))


def concept_similarity(a: str, b: str) -> float:
    """Do these two describe the same *job*? 0.0 - 1.0.

    Blends Jaccard (penalises unrelated extras) with the overlap coefficient
    (tolerates length mismatch), so a terse title still matches a verbose one.
    """
    a_stems, b_stems = stems(a), stems(b)
    if not a_stems or not b_stems:
        return 0.0
    return round(0.5 * jaccard(a_stems, b_stems) + 0.5 * overlap_coefficient(a_stems, b_stems), 4)


def feature_similarity(
    title_a: str, desc_a: str, title_b: str, desc_b: str
) -> float:
    """Concept similarity for a *feature*, which has a title and a description.

    Comparing the concatenated title+description alone lets a long marketing
    blurb drown the title: "Mood detection" and "Sentiment analysis" are the
    same job and score 1.0 on their titles, but only 0.27 once two verbose,
    differently-worded descriptions are appended. Taking the stronger of the
    two readings keeps the crisp title signal without discarding the extra
    evidence a description provides when the titles are unhelpful.
    """
    title_score = concept_similarity(title_a, title_b)
    full_score = concept_similarity(
        f"{title_a}. {desc_a}".strip(), f"{title_b}. {desc_b}".strip()
    )
    return round(max(title_score, full_score), 4)


def expression_similarity(a: str, b: str) -> float:
    """Is the *wording* the same? 0.0 - 1.0.

    Two signals, both word-aware:

    - character 4-gram Dice, which catches near-verbatim copying including
      light paraphrase and typo'd reproductions;
    - a *word-level* sequence ratio, which rewards shared ordering.

    Character-level SequenceMatcher is deliberately NOT used. Any two English
    sentences of similar length score 0.33-0.40 on it purely from shared
    letters, and that noise floor propagated straight into the IP risk score
    as phantom risk for unrelated features.
    """
    a_norm, b_norm = normalize(a), normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    ngram_score = dice(char_ngrams(a), char_ngrams(b))
    word_score = SequenceMatcher(
        None, a_norm.split(), b_norm.split(), autojunk=False
    ).ratio()
    return round(max(ngram_score, word_score), 4)


def name_similarity(a: str, b: str) -> float:
    """Are two names confusable? Drives the trademark signal, not copyright."""
    a_norm, b_norm = normalize(a), normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    edit_score = SequenceMatcher(None, a_norm, b_norm, autojunk=False).ratio()
    token_score = overlap_coefficient(set(a_norm.split()), set(b_norm.split()))
    return round(max(edit_score, token_score), 4)
