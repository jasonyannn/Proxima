import json
import re
import requests
from typing import Any, Iterator

try:
    from .database import DatabaseManager
except ImportError:  # pragma: no cover
    from database import DatabaseManager


class ProximaAgent:
    def __init__(self, database: DatabaseManager | None = None, system_prompt: str = "", ollama_host: str = "http://localhost:11434") -> None:
        self.database = database or DatabaseManager()
        self.system_prompt = system_prompt
        self.ollama_host = ollama_host
        self.model = "llama3.2"

    def understand_intent(self, user_input: str) -> dict[str, Any]:
        text = user_input.strip()
        if not text:
            return {"type": "unknown", "title": "", "summary": ""}

        lowered = text.lower()

        if re.search(r"(asking for|want|request(ed)?|customers? .* for|have .* customers?)", lowered):
            title = self._extract_feature_title(text)
            evidence = self._extract_customer_count(text)
            impact = "High" if evidence >= 10 else "Medium"
            priority = "High" if evidence >= 10 else "Medium"
            status = "Backlog"
            description = f"Customer demand signal: {evidence} customer request(s) recorded." if evidence else "Customer request for this feature."
            return {
                "type": "Feature",
                "title": title or "New Feature",
                "description": description,
                "priority": priority,
                "impact": impact,
                "effort": "Medium",
                "status": status,
                "evidence": evidence,
            }

        if re.search(r"(bug|error|issue|broken|crash|fail|failing|not working)", lowered):
            title = self._extract_bug_title(text)
            return {
                "type": "Bug",
                "title": title or "Reported Bug",
                "description": text,
                "severity": "High" if re.search(r"(critical|urgent|crash|data loss|security)", lowered) else "Medium",
                "status": "Open",
            }

        if re.search(r"(feedback|customer said|users said|suggestion|comment|response)", lowered):
            source = "customer" if "customer" in lowered else "user"
            return {
                "type": "Feedback",
                "title": "Customer Feedback",
                "source": source,
                "content": text,
                "sentiment": self._infer_sentiment(lowered),
            }

        return {"type": "Unknown", "title": "General Input", "summary": text}

    def _extract_feature_title(self, text: str) -> str:
        patterns = [
            r"(?:asking for|want|request(?:ed)?|needs?)\s+(?:a\s+)?([A-Za-z0-9][A-Za-z0-9\s-]+)",
            r"(?:customers?\s+(?:have|had|asking).*?for)\s+([A-Za-z0-9][A-Za-z0-9\s-]+)",
            r"(?:for)\s+([A-Za-z0-9][A-Za-z0-9\s-]+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if title:
                    return title.title()
        return "Requested Feature"

    def _extract_customer_count(self, text: str) -> int:
        match = re.search(r"(\d+)\s+customers?", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 0

    def _extract_bug_title(self, text: str) -> str:
        title = re.sub(r"^(?:there\s+is\s+|we\s+have\s+|report\s+)?", "", text, flags=re.IGNORECASE)
        title = title.strip()
        if title.lower().startswith("bug"):
            title = title[3:].strip()
        return title.title() or "Reported Bug"

    def _infer_sentiment(self, text: str) -> str:
        if re.search(r"(love|great|excellent|happy|positive|good|amazing)", text):
            return "positive"
        if re.search(r"(hate|bad|terrible|angry|frustrated|poor|negative)", text):
            return "negative"
        return "neutral"

    def generate_response(self, user_input: str, conversation_history: list[dict] = None) -> str:
        """Answer the user.

        Pure question-in, answer-out: nothing is written to the database here.
        What the message implies is offered to the user as a save action in the
        chat instead, so product memory only ever grows on a deliberate click.
        """
        return "".join(self.stream_response(user_input, conversation_history))

    def stream_response(
        self, user_input: str, conversation_history: list[dict] = None
    ) -> Iterator[str]:
        """Yield the reply in pieces, as the model writes them.

        Streaming is what makes a long answer survive: the read timeout then
        applies between chunks rather than to the whole generation, so an
        analysis that takes two minutes is no longer indistinguishable from a
        dead server.
        """
        prompt = self._build_prompt(user_input, conversation_history)

        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    # Sampling settings belong under `options`; Ollama ignores
                    # them at the top level.
                    "options": {"temperature": 0.3},
                },
                # (connect, read-between-chunks) — not a budget for the answer.
                timeout=(10, 120),
                stream=True,
            )
            response.raise_for_status()

            produced = False
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    yield self._unreachable(chunk["error"])
                    return
                piece = chunk.get("response", "")
                if piece:
                    produced = True
                    yield piece
                if chunk.get("done"):
                    break

            if not produced:
                yield "The model returned an empty response. Try sending the message again."
        except (requests.exceptions.RequestException, json.JSONDecodeError) as exc:
            # Say what went wrong. A canned stand-in reads like an answer and
            # hides the fact that the model was never reached.
            yield self._unreachable(exc)

    def _unreachable(self, detail: object) -> str:
        return (
            f"⚠️ **I could not reach the local model.** ({detail})\n\n"
            "Proxima answers through Ollama on "
            f"`{self.ollama_host}`. Start it with `ollama serve` "
            f"(and `ollama pull {self.model}`), then send the message again."
        )

    def _build_prompt(self, user_input: str, conversation_history: list[dict] = None) -> str:
        """System prompt, recent turns, then the question."""
        conversation_text = ""
        for msg in (conversation_history or [])[-5:]:  # last few turns for context
            conversation_text += (
                f"User: {msg.get('user', '')}\nAssistant: {msg.get('agent') or ''}\n"
            )
        if conversation_text:
            conversation_text = "\nPrevious conversation:\n" + conversation_text

        return f"{self.system_prompt}{conversation_text}\n\nUser: {user_input}\n\nAssistant:"


# ----------------------------------------------------------- save suggestions

# Cues that introduce a rival by name: "compared with X", "competitor X".
_COMPETITOR_CUE = re.compile(
    r"\b(?:competitors?|competing\s+with|compared?\s+(?:with|to|against)|"
    r"compare\s+(?:us\s+)?(?:with|to|against)|versus|vs\.?|rivals?|"
    r"alternatives?\s+to|similar\s+to|like)\b",
    re.IGNORECASE,
)

# A capitalised run of up to three words — the shape of a product or company.
_PROPER_NOUN = re.compile(r"\b([A-Z][A-Za-z0-9&.'’-]+(?:\s+[A-Z][A-Za-z0-9&.'’-]+){0,2})")

# Capitalised words that start sentences or head sections in a brief, and so
# routinely follow a cue without naming anybody.
_NOT_A_NAME = {
    "a", "ai", "an", "analyse", "analyze", "and", "api", "b2b", "b2c", "current",
    "customer", "customers", "design", "do", "evaluate", "feature", "features",
    "high", "hosts", "i", "identify", "if", "it", "key", "low", "marketplace",
    "medium", "my", "our", "output", "overall", "premium", "primary", "product",
    "products", "questions", "recommend", "recommended", "saas", "separate",
    "start", "status", "the", "their", "then", "they", "this", "trademark", "ui",
    "us", "user", "users", "ux", "we", "what", "when", "whether", "which", "your",
}


# What may sit between two names that are part of one list.
_LIST_SEPARATOR = re.compile(r"[\s,]*(?:and|&|or|,)?[\s,]*", re.IGNORECASE)


def _clean_name(candidate: str) -> str | None:
    """Trim a proper-noun run down to the part that plausibly names a company."""
    words = candidate.split()
    while words and words[-1].lower() in _NOT_A_NAME:
        words.pop()
    if not words or words[0].lower() in _NOT_A_NAME:
        return None
    name = " ".join(words).strip(".'’-")
    # Single letters and bare acronyms are noise, not brands.
    if len(name) < 3 or name.isupper() and len(name) <= 3:
        return None
    return name


def detect_competitors(text: str, known: set[str] | None = None) -> list[str]:
    """Names introduced as rivals in `text`, minus the ones already on file."""
    known_lower = {n.lower() for n in (known or set())}
    found: list[str] = []

    for cue in _COMPETITOR_CUE.finditer(text):
        # Look just past the cue: "compared with >>Airbnb<< Your task ...".
        window = text[cue.end(): cue.end() + 80]

        end_of_previous = None
        for match in _PROPER_NOUN.finditer(window):
            # Keep walking only while the names are still being listed —
            # "Notion and Linear", "Booking.com, Vrbo". Anything else ends it.
            if end_of_previous is not None and not _LIST_SEPARATOR.fullmatch(
                window[end_of_previous:match.start()]
            ):
                break
            end_of_previous = match.end()

            name = _clean_name(match.group(1))
            if not name:
                break
            if name.lower() in known_lower or name.lower() in {f.lower() for f in found}:
                continue
            found.append(name)

    return found[:3]


def detect_saveable(
    text: str, agent: "ProximaAgent", known_competitors: set[str] | None = None
) -> list[dict[str, Any]]:
    """What this message offers to put in product memory, if the user wants it.

    Suggestions only — nothing here touches the database. That is what lets the
    matching stay loose: a wrong guess costs a chip the user ignores, not a junk
    row in the backlog.
    """
    suggestions: list[dict[str, Any]] = []

    for name in detect_competitors(text, known_competitors):
        suggestions.append({"kind": "competitor", "label": f"competitor:{name}", "name": name})

    intent = agent.understand_intent(text)
    kind = str(intent.get("type", "")).lower()
    if kind in {"feature", "bug", "feedback"}:
        entry = dict(intent)
        entry["kind"] = kind
        entry["label"] = f"{kind}:{intent.get('title', '')}"
        suggestions.append(entry)

    return suggestions
