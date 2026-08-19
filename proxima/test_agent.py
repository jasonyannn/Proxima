#!/usr/bin/env python3
"""Quick test of the Proxima agent with Ollama."""

import sys
sys.path.insert(0, "proxima")

from agent import ProximaAgent
from prompt import SYSTEM_PROMPT
from database import DatabaseManager

# Initialize
db = DatabaseManager()
db.init_db()
agent = ProximaAgent(database=db, system_prompt=SYSTEM_PROMPT)

# Test with the example prompt
test_input = "Customers keep asking for dark mode..."
print(f"User: {test_input}")
print("-" * 60)

try:
    response = agent.generate_response(test_input)
    print(f"Agent: {response}")
except Exception as e:
    print(f"Error: {e}")
    print("\nMake sure Ollama is running: ollama serve")
