import re
import requests
from typing import Any

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
        intent = self.understand_intent(user_input)
        memory_entry = self.maybe_modify_database(intent)

        # Build the prompt with context
        context = ""
        if memory_entry:
            context = f"\nRecognized: {memory_entry['type']}\nTitle: {memory_entry['title']}\nPriority: {memory_entry.get('priority', 'N/A')}\nImpact: {memory_entry.get('impact', 'N/A')}\nStatus: {memory_entry.get('status', 'N/A')}\nSaved to product memory."

        # Call Ollama with the system prompt and conversation history
        try:
            response_text = self._query_ollama(user_input, context, conversation_history)
            return response_text
        except Exception as e:
            # Fallback if Ollama is unavailable
            default_response = f"Understood: {intent.get('type', 'Unknown')}"
            if context:
                default_response += context
            return default_response

    def _query_ollama(self, user_input: str, context: str = "", conversation_history: list[dict] = None) -> str:
        """Query Ollama with the system prompt, conversation history, and user input."""
        if conversation_history is None:
            conversation_history = []
        
        # Build conversation context
        conversation_text = ""
        if conversation_history:
            conversation_text = "\nPrevious conversation:\n"
            for msg in conversation_history[-5:]:  # Last 5 messages for context
                conversation_text += f"User: {msg.get('user', '')}\nAssistant: {msg.get('agent', '')}\n"
        
        prompt = f"{self.system_prompt}{conversation_text}\n\nUser: {user_input}{context}\n\nAssistant:"
        
        try:
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "No response from model").strip()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to Ollama at {self.ollama_host}: {str(e)}")

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
