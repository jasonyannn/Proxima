import re
from typing import Any

try:
    from .database import DatabaseManager
except ImportError:  # pragma: no cover
    from database import DatabaseManager


class ProximaAgent:
    def __init__(self, database: DatabaseManager | None = None, system_prompt: str = "") -> None:
        self.database = database or DatabaseManager()
        self.system_prompt = system_prompt

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

    def generate_response(self, user_input: str) -> str:
        intent = self.understand_intent(user_input)
        memory_entry = self.maybe_modify_database(intent)

        if self.system_prompt:
            prefix = self.system_prompt
        else:
            prefix = "You are Proxima, a product operations assistant."

        if memory_entry is None:
            return f"{prefix}\n\nUnderstood: {intent.get('type', 'Unknown')}\nInput: {user_input}"

        return (
            f"{prefix}\n\nRecognized: {memory_entry['type']}\n"
            f"Title: {memory_entry['title']}\n"
            f"Priority: {memory_entry.get('priority', 'N/A')}\n"
            f"Impact: {memory_entry.get('impact', 'N/A')}\n"
            f"Status: {memory_entry.get('status', 'N/A')}\n"
            f"Saved to product memory."
        )

    def maybe_modify_database(self, intent: dict[str, Any]) -> dict[str, Any] | None:
        entry_type = str(intent.get("type", "")).lower()

        if entry_type == "feature":
            feature_id = self.database.create_feature(
                title=intent["title"],
                description=intent.get("description"),
                priority=intent.get("priority", "medium"),
                impact=intent.get("impact", "medium"),
                effort=intent.get("effort", "medium"),
                status=intent.get("status", "planned"),
            )
            intent["id"] = feature_id
            return intent

        if entry_type == "bug":
            bug_id = self.database.create_bug(
                title=intent["title"],
                description=intent.get("description"),
                severity=intent.get("severity", "medium"),
                status=intent.get("status", "open"),
            )
            intent["id"] = bug_id
            return intent

        if entry_type == "feedback":
            feedback_id = self.database.create_feedback(
                source=intent.get("source"),
                content=intent.get("content", ""),
                sentiment=intent.get("sentiment", "neutral"),
            )
            intent["id"] = feedback_id
            return intent

        return None
