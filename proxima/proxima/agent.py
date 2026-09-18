# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

import json
import re
import requests
from typing import Any, Iterator

try:
    from .database import DatabaseManager
    from . import visuals
except ImportError:  # pragma: no cover
    from database import DatabaseManager
    import visuals


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
        """System prompt, recent turns, the question, then the visual reminder.

        The reminder goes *after* the question rather than into the system
        prompt because that is the only place a 3B model reliably acts on it:
        by the time it starts writing, the formatting rules at the top are
        thousands of characters behind it, and it falls back on the markdown
        table it has seen a million of. Measured, not assumed — llama3.2
        ignored the system-prompt version of this instruction outright.
        """
        conversation_text = ""
        for msg in (conversation_history or [])[-5:]:  # last few turns for context
            conversation_text += (
                f"User: {msg.get('user', '')}\nAssistant: {msg.get('agent') or ''}\n"
            )
        if conversation_text:
            conversation_text = "\nPrevious conversation:\n" + conversation_text

        reminder = visuals.turn_reminder(user_input)
        return (
            f"{self.system_prompt}{conversation_text}"
            f"\n\nUser: {user_input}\n{reminder}\nAssistant:"
        )

    def research_competitor(self, name: str, limit: int = 10) -> list[dict[str, str]]:
        """What the model remembers of a rival's feature set.

        This is recall, not research: the model has no browser and no access to
        the company's site, so the list is what a well-read person would say
        from memory — roughly right about a well-known product, capable of
        being wrong or out of date about any of it. Everything it produces is
        labelled as recalled wherever it is shown, and the analysers treat it
        as a starting point to correct, not a source of truth.
        """
        instruction = (
            f"List the main product features of {name}, the software product, "
            "as a product manager would describe them for a competitive "
            "comparison.\n\n"
            'Return ONLY JSON: {"features": [{"name": "...", "category": "...", '
            '"description": "..."}]}\n\n'
            "Rules:\n"
            f"- At most {limit} features, the ones {name} is best known for.\n"
            "- name: 2-5 words, the capability itself, not marketing copy.\n"
            "- category: one or two words, e.g. Payments, Storefront, "
            "Analytics, Shipping.\n"
            "- description: one sentence on what it does for the user.\n"
            "- Only features you are confident this product actually has. If "
            "you do not recognise the product, return an empty list.\n\nJSON:"
        )

        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": instruction,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 900},
                },
                timeout=(10, 120),
            )
            response.raise_for_status()
            parsed = json.loads(response.json().get("response", ""))
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
            return []

        rows = parsed.get("features") if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            return []

        features: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows[:limit]:
            if isinstance(row, str):
                row = {"name": row}
            if not isinstance(row, dict):
                continue
            title = " ".join(str(row.get("name") or "").split())[:80]
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            features.append(
                {
                    "name": title,
                    "category": " ".join(str(row.get("category") or "").split())[:40],
                    "description": " ".join(str(row.get("description") or "").split())[:400],
                }
            )
        return features

    def profile_product(self, conversation: list[dict], limit: int = 10) -> dict[str, Any]:
        """Read the whole chat and describe the product being discussed.

        One pass over the conversation, rather than message by message: what a
        product is only becomes clear across several turns, and the features
        worth filing are usually spread over all of them.
        """
        transcript = "\n".join(
            f"User: {msg.get('user', '')}" for msg in conversation[-8:] if msg.get("user")
        )
        if not transcript.strip():
            return {}

        instruction = (
            "Below is what someone told an assistant about the product they are "
            "building. Describe that product.\n\n"
            'Return ONLY JSON: {"summary": "...", "features": [{"title": "...", '
            '"description": "..."}]}\n\n'
            "Rules:\n"
            "- summary: one sentence describing their product.\n"
            f"- features: at most {limit} capabilities THEIR product has or is "
            "meant to have, taken from what they wrote. Title of 2-5 words.\n"
            "- Never list a competitor's features here, only theirs.\n"
            "- If they described no product, return empty values.\n\n"
            f"Conversation:\n{transcript}\n\nJSON:"
        )

        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": instruction,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 800},
                },
                timeout=(10, 120),
            )
            response.raise_for_status()
            parsed = json.loads(response.json().get("response", ""))
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
            return {}

        if not isinstance(parsed, dict):
            return {}

        features = []
        seen: set[str] = set()
        for row in (parsed.get("features") or [])[:limit]:
            if isinstance(row, str):
                row = {"title": row}
            if not isinstance(row, dict):
                continue
            title = " ".join(str(row.get("title") or "").split())[:80]
            if not title or title.lower() in seen or not _plausible_title(title):
                continue
            seen.add(title.lower())
            features.append(
                {
                    "title": title,
                    "description": " ".join(str(row.get("description") or "").split())[:400],
                }
            )

        return {
            "summary": " ".join(str(parsed.get("summary") or "").split())[:300],
            "features": features,
        }

    def competitors_in_conversation(self, conversation: list[dict], limit: int = 6) -> list[dict[str, str]]:
        """Every rival named anywhere in a chat, read in one pass.

        Per-message extraction misses the ones mentioned before the chat made
        it clear what the product even was, and re-offers ones already dealt
        with. Reading the whole transcript at once catches both.
        """
        transcript = "\n".join(
            f"- {msg.get('user', '')}" for msg in conversation[-12:] if msg.get("user")
        )
        if not transcript.strip():
            return []

        instruction = (
            "Below is what someone told an assistant while working on their "
            "product. List every existing company or product they named.\n\n"
            'Return ONLY JSON: {"competitors": [{"name": "...", "positioning": "..."}]}\n\n'
            "Rules:\n"
            f"- At most {limit}. Use the proper brand spelling.\n"
            "- positioning: a short phrase for what that company is.\n"
            "- A product they compare themselves to counts, however they phrase "
            "it: \"the new Shopify\", \"like Airbnb but for parking\", \"an Uber "
            "for laundry\", \"similar to Notion\" — Shopify, Airbnb, Uber and "
            "Notion are all competitors here. So does one they say they are "
            "worried about, or want to take customers from.\n"
            "- Their own product is usually unnamed, or is the thing being "
            "built. Do not invent a name for it, and do not list it.\n"
            "- Only names that actually appear in the text. Never invent one.\n\n"
            f"Notes:\n{transcript}\n\nJSON:"
        )
        rows = self._json_list(instruction, "competitors", limit)

        # The keyword rules are narrower but never hesitate: they catch the
        # "compared with X" phrasings whatever the model decides to make of
        # them. Cheap insurance against a shy answer.
        for name in detect_competitors(transcript):
            if not any(str(r.get("name", "")).lower() == name.lower() for r in rows):
                rows.append({"name": name, "positioning": ""})

        # Only names the chat really contains: the model will otherwise round a
        # marketplace up to Amazon.
        haystack = transcript.lower()
        found = []
        for row in rows:
            name = " ".join(str(row.get("name") or "").split())[:80]
            if name and name.lower() in haystack:
                found.append(
                    {
                        "name": name,
                        "positioning": " ".join(str(row.get("positioning") or "").split())[:200],
                    }
                )
        return found

    def suggest_rivals(
        self, summary: str, exclude: set[str] | None = None, limit: int = 6
    ) -> list[dict[str, str]]:
        """Rivals the chat never mentioned, for the ones you have not thought of.

        The opposite job to the scan above: here the model is asked to go
        beyond the text, so nothing it says can be checked against the chat.
        Everything comes back as a proposal to accept or ignore.
        """
        summary = " ".join(str(summary or "").split())
        if len(summary) < 12:
            return []

        skip = ", ".join(sorted(exclude or set())) or "none"
        instruction = (
            f"A product is described as: {summary}\n\n"
            "Name the real, existing products that compete with it most "
            "directly — the ones its team should be watching.\n\n"
            'Return ONLY JSON: {"competitors": [{"name": "...", "positioning": '
            '"...", "why": "..."}]}\n\n'
            "Rules:\n"
            f"- At most {limit}, most relevant first.\n"
            f"- Do not include any of these, they are already known: {skip}.\n"
            "- Only products that genuinely exist. If you are not confident a "
            "name is real, leave it out.\n"
            "- why: one short phrase on why they compete.\n\nJSON:"
        )
        rows = self._json_list(instruction, "competitors", limit)

        skip_lower = {name.lower() for name in (exclude or set())}
        out = []
        seen: set[str] = set()
        for row in rows:
            name = " ".join(str(row.get("name") or "").split())[:80]
            key = name.lower()
            if not name or key in skip_lower or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "name": name,
                    "positioning": " ".join(str(row.get("positioning") or "").split())[:200],
                    "why": " ".join(str(row.get("why") or "").split())[:200],
                }
            )
        return out

    def _json_list(self, instruction: str, key: str, limit: int) -> list[dict]:
        """Run a JSON-constrained prompt and return one list from the result."""
        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": instruction,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 700},
                },
                timeout=(10, 120),
            )
            response.raise_for_status()
            parsed = json.loads(response.json().get("response", ""))
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
            return []

        rows = parsed.get(key) if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            return []
        return [
            {"name": row} if isinstance(row, str) else row
            for row in rows[:limit]
            if isinstance(row, (str, dict))
        ]

    def suggest_tickets(self, conversation: list[dict], limit: int = 8) -> list[dict[str, Any]]:
        """Work items implied by a conversation.

        A feature is what the product does; a ticket is a piece of work someone
        picks up. The chat usually contains both — "sign-out fails on refresh"
        is a ticket, "sellers design their own shop" is a feature — so this
        looks only for the second kind.
        """
        transcript = "\n".join(
            f"- {msg.get('user', '')}" for msg in conversation[-10:] if msg.get("user")
        )
        if not transcript.strip():
            return []

        instruction = (
            "Below is what someone said while working on their product. List "
            "the pieces of work this implies — the things a team would put on "
            "a board and pick up.\n\n"
            'Return ONLY JSON: {"tickets": [{"title": "...", "description": '
            '"...", "priority": "High|Medium|Low", "kind": "Bug|Feature|Chore"}]}\n\n'
            "Rules:\n"
            f"- At most {limit}, most valuable first.\n"
            "- title: an imperative of 3-8 words — \"Fix sign-out after refresh\", "
            "\"Add bulk CSV export\".\n"
            "- description: one or two sentences on what doing it involves.\n"
            "- Only work the text actually calls for. Do not pad the list with "
            "generic project tasks nobody mentioned.\n"
            "- If nothing needs doing, return an empty list.\n\n"
            f"Notes:\n{transcript}\n\nJSON:"
        )

        tickets = []
        seen: set[str] = set()
        for row in self._json_list(instruction, "tickets", limit):
            title = " ".join(str(row.get("title") or "").split())[:120]
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            priority = str(row.get("priority") or "Medium").title()
            tickets.append(
                {
                    "title": title,
                    "description": " ".join(str(row.get("description") or "").split())[:500],
                    "priority": priority if priority in {"High", "Medium", "Low"} else "Medium",
                    "kind": str(row.get("kind") or "").title(),
                }
            )
        return tickets

    def polish_prompt(self, text: str) -> str:
        """Tidy a half-written message: spelling, grammar, punctuation.

        Runs on the local model, so it is free and offline — there is no API
        bill for fixing a typo. Returns the text unchanged whenever the result
        looks like anything other than a careful edit: a rewrite that loses the
        user's meaning is far worse than leaving a comma out of place.
        """
        original = text.strip()
        if len(original) < 12:
            return text  # nothing to work with yet

        instruction = (
            "Correct the spelling, grammar and punctuation of the message "
            "below.\n\n"
            "Rules:\n"
            "- Keep the meaning, tone and every specific detail identical.\n"
            "- Keep the author's own words wherever they are already correct.\n"
            "- Do not answer the message, comment on it, or add anything to it.\n"
            "- Do not translate it or change its language.\n"
            "- If it is already correct, return it unchanged.\n\n"
            'Return ONLY JSON: {"corrected": "..."}\n\n'
            f"Message:\n{original}\n\nJSON:"
        )

        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": instruction,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_predict": 700},
                },
                timeout=(5, 60),
            )
            response.raise_for_status()
            corrected = json.loads(response.json().get("response", "")).get("corrected")
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError, AttributeError):
            return text

        if not isinstance(corrected, str):
            return text
        corrected = corrected.strip()

        # A correction stays roughly the same size. Anything else is the model
        # answering the message instead of editing it.
        if not corrected or not (0.6 <= len(corrected) / len(original) <= 1.6):
            return text
        return corrected

    def predict_continuation(self, text: str, max_words: int = 8) -> str:
        """The next few words of a sentence the user is still typing.

        Kept deliberately short: a long guess is a distraction, and a wrong
        short one costs nothing to ignore.
        """
        tail = text.strip()
        if len(tail) < 8 or tail.endswith((".", "!", "?")):
            return ""

        instruction = (
            "You are an autocomplete. Continue the unfinished product-management "
            "message with at most "
            f"{max_words} more words. Write only the continuation — no quotes, "
            "no restatement of what is already written, no commentary. If "
            "nothing sensible follows, write nothing.\n\n"
            f"Unfinished message: {tail}\n\nContinuation:"
        )

        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": instruction,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": max_words * 4,
                        "stop": ["\n"],
                    },
                },
                timeout=(5, 30),
            )
            response.raise_for_status()
            guess = str(response.json().get("response", "")).strip()
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
            return ""

        guess = guess.strip().strip('"').strip()
        # Models like to echo the prompt back before continuing it.
        if guess.lower().startswith(tail.lower()[:40]):
            guess = guess[len(tail):].strip()
        words = guess.split()
        if not words:
            return ""
        guess = " ".join(words[:max_words])
        # Join with a space unless the user is mid-word.
        return guess if text.endswith(" ") else " " + guess

    def extract_entities(self, text: str) -> dict[str, list]:
        """Ask the model what this message mentions that could be filed.

        The keyword rules below only catch a name that is capitalised and
        introduced by a cue word, which is not how people actually write —
        "is this a copyright risk to shopify" names a rival and matches none of
        them. The model reads it the way a person would.

        Returns empty on any trouble; the caller keeps whatever the rules found.
        """
        instruction = (
            "Read the product message below and list what it mentions.\n\n"
            "Return ONLY a JSON object, no prose, in exactly this shape:\n"
            '{"competitors": [{"name": "...", "positioning": "..."}], '
            '"features": [{"title": "...", "description": "..."}], '
            '"bugs": [{"title": "...", "description": "..."}]}\n\n'
            "Rules:\n"
            "- competitors: existing companies or products named in the message "
            "as rivals, comparisons or platforms to be like. Use their proper "
            "brand spelling. Never invent one, and never list the user's own "
            "product.\n"
            "- features: capabilities the message describes the product as "
            "having, needing, or being asked for — including ones described in "
            "passing (\"users can design their own storefront\"). Use the "
            "message's own words, and give each a title of at most six words. "
            "Do not invent capabilities the message never mentions; if there "
            "are none, return an empty list.\n"
            "- bugs: things reported as broken.\n"
            "- Use an empty list where there is nothing. Maximum 4 per list.\n\n"
            f"Message:\n{text}\n\nJSON:"
        )

        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": instruction,
                    "stream": False,
                    "format": "json",  # Ollama constrains the decode to valid JSON
                    "options": {"temperature": 0, "num_predict": 400},
                },
                timeout=(10, 90),
            )
            response.raise_for_status()
            raw = response.json().get("response", "")
            parsed = json.loads(raw)
        except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
            return {}

        if not isinstance(parsed, dict):
            return {}

        def rows(key: str) -> list[dict]:
            value = parsed.get(key)
            if not isinstance(value, list):
                return []
            # The model sometimes answers with bare strings instead of objects.
            out = []
            for entry in value[:4]:
                if isinstance(entry, str):
                    out.append({"name": entry, "title": entry})
                elif isinstance(entry, dict):
                    out.append(entry)
            return out

        return {
            "competitors": rows("competitors"),
            "features": rows("features"),
            "bugs": rows("bugs"),
        }


# ----------------------------------------------------------- save suggestions

# Cues that introduce a rival by name: "compared with X", "competitor X".
_COMPETITOR_CUE = re.compile(
    r"\b(?:competitors?|competing\s+with|compared?\s+(?:with|to|against)|"
    r"compare\s+(?:us\s+)?(?:with|to|against)|versus|vs\.?|rivals?|"
    r"alternatives?\s+to|similar\s+to|like)\b",
    re.IGNORECASE,
)

# A capitalised run of up to three words — the shape of a product or company.
# A dot only joins a name when it is internal ("Booking.com"). A dot before a
# space ends the sentence, and the capitalised word after it starts a new one —
# without this, "compared with Airbnb. Give me..." reads as "Airbnb. Give".
_WORD = r"[A-Z][A-Za-z0-9&'’-]*(?:\.[A-Za-z0-9][A-Za-z0-9&'’-]*)*"
_PROPER_NOUN = re.compile(rf"\b({_WORD}(?:\s+{_WORD}){{0,2}})")

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


# A backlog title names a thing. A sentence fragment starts with one of these.
_FRAGMENT_OPENERS = {
    "a", "an", "and", "are", "as", "at", "be", "can", "could", "do",
    "does", "for", "how", "i", "if", "in", "is", "it", "me", "my", "of", "on",
    "or", "our", "should", "that", "the", "their", "them", "they", "this", "to",
    "us", "we", "what", "whether", "which", "why", "would", "you", "your",
}


def _plausible_title(title: str) -> bool:
    """Does this read as a backlog entry, or as a slice of someone's sentence?"""
    words = str(title or "").split()
    if not (1 <= len(words) <= 6):
        return False
    if words[0].lower() in _FRAGMENT_OPENERS:
        return False
    return words[-1].lower() not in _FRAGMENT_OPENERS


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
        suggestions.append(
            {
                "kind": "competitor",
                "label": f"competitor:{name}",
                "name": name,
                "source": "rules",
            }
        )

    intent = agent.understand_intent(text)
    kind = str(intent.get("type", "")).lower()
    if kind in {"feature", "bug"} and not _plausible_title(intent.get("title", "")):
        # The rules build a title by slicing the sentence, which on a question
        # yields "You To Analyse Whether Building This Could Create Copyright".
        # Offer nothing rather than that; the model reads the message shortly
        # afterwards and usually writes a real title.
        kind = ""
    if kind in {"feature", "bug", "feedback"}:
        entry = dict(intent)
        entry["kind"] = kind
        entry["label"] = f"{kind}:{intent.get('title', '')}"
        entry["source"] = "rules"
        suggestions.append(entry)

    return suggestions


def suggestions_from_model(
    text: str,
    agent: "ProximaAgent",
    known_competitors: set[str] | None = None,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The model's reading of the message, as save chips the rules missed.

    Runs after the answer, so it costs the user no waiting, and only ever adds
    to what `detect_saveable` already offered.
    """
    extracted = agent.extract_entities(text)
    if not extracted:
        return []

    known_lower = {n.lower() for n in (known_competitors or set())}
    seen = {s["label"].lower() for s in (existing or [])}
    haystack = text.lower()
    additions: list[dict[str, Any]] = []

    def keep(label: str) -> bool:
        if label.lower() in seen:
            return False
        seen.add(label.lower())
        return True

    for row in extracted.get("competitors", []):
        name = str(row.get("name") or "").strip()
        if not name or name.lower() in known_lower or len(name) < 2:
            continue
        # Asked not to invent rivals, the model does it anyway — "dark mode"
        # comes back as Apple. A name nobody typed is not a mention.
        if name.lower() not in haystack:
            continue
        label = f"competitor:{name}"
        if keep(label):
            additions.append(
                {
                    "kind": "competitor",
                    "source": "model",
                    "label": label,
                    "name": name,
                    "positioning": str(row.get("positioning") or "").strip(),
                }
            )

    for row in extracted.get("features", []):
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        label = f"feature:{title}"
        if keep(label):
            additions.append(
                {
                    "kind": "feature",
                    "source": "model",
                    "label": label,
                    "title": title,
                    "description": str(row.get("description") or "").strip(),
                    "priority": "Medium",
                    "impact": "Medium",
                    "effort": "Medium",
                    "status": "Backlog",
                }
            )

    for row in extracted.get("bugs", []):
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        label = f"bug:{title}"
        if keep(label):
            additions.append(
                {
                    "kind": "bug",
                    "source": "model",
                    "label": label,
                    "title": title,
                    "description": str(row.get("description") or "").strip(),
                    "severity": "Medium",
                    "status": "Open",
                }
            )

    return additions
