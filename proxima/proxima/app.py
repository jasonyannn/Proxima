import streamlit as st
from datetime import datetime

try:
    from .agent import ProximaAgent
    from .database import DatabaseManager
    from .prompt import SYSTEM_PROMPT
except ImportError:  # pragma: no cover
    from agent import ProximaAgent
    from database import DatabaseManager
    from prompt import SYSTEM_PROMPT


def get_agent() -> ProximaAgent:
    db = DatabaseManager()
    db.init_db()
    return ProximaAgent(database=db, system_prompt=SYSTEM_PROMPT)


st.set_page_config(
    page_title="Proxima PM Agent",
    page_icon="🤖",
    layout="wide",
)

# Initialize session state
if "chats" not in st.session_state:
    st.session_state.chats = {}
    
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = None

# Sidebar for chat management
with st.sidebar:
    st.title("💬 Chats")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("➕ New Chat", use_container_width=True):
            new_chat_id = f"chat_{len(st.session_state.chats)}_{datetime.now().timestamp()}"
            st.session_state.chats[new_chat_id] = {"messages": [], "created": datetime.now()}
            st.session_state.current_chat_id = new_chat_id
            st.rerun()
    
    st.divider()
    
    # List all chats
    if st.session_state.chats:
        for chat_id, chat_data in st.session_state.chats.items():
            chat_preview = f"Chat {list(st.session_state.chats.keys()).index(chat_id) + 1}"
            if chat_data["messages"]:
                first_msg = chat_data["messages"][0].get("user", "")[:30]
                chat_preview = first_msg + "..." if len(first_msg) > 25 else first_msg
            
            if st.button(chat_preview, use_container_width=True, key=f"select_{chat_id}"):
                st.session_state.current_chat_id = chat_id
                st.rerun()
    else:
        st.info("No chats yet. Create a new one to get started!")

# Main chat area
st.title("🤖 PRODUCT MANAGEMENT AGENT")
st.caption("Turn customer feedback into structured product decisions.")

# Create first chat if none exist
if not st.session_state.chats:
    new_chat_id = f"chat_0_{datetime.now().timestamp()}"
    st.session_state.chats[new_chat_id] = {"messages": [], "created": datetime.now()}
    st.session_state.current_chat_id = new_chat_id

current_chat = st.session_state.chats.get(st.session_state.current_chat_id, {})
messages = current_chat.get("messages", [])

# Display chat history
if messages:
    st.subheader("Conversation")
    for item in messages:
        with st.chat_message("user"):
            st.markdown(item["user"])
        with st.chat_message("assistant"):
            st.markdown(item["agent"])
else:
    st.info("Start a conversation! Try: 'We've had 20 customers asking for dark mode.'")

# Input area
st.divider()
col1, col2 = st.columns([5, 1])

with col1:
    user_input = st.text_input(
        "Message Proxima...",
        placeholder="Customers keep asking for dark mode...",
        key="user_input",
    )

with col2:
    send_button = st.button("Send", use_container_width=True)

if send_button and user_input.strip():
    agent = get_agent()
    
    with st.spinner("Proxima is thinking..."):
        response = agent.generate_response(user_input, conversation_history=messages)
    
    # Add to current chat
    if st.session_state.current_chat_id in st.session_state.chats:
        st.session_state.chats[st.session_state.current_chat_id]["messages"].append({
            "user": user_input,
            "agent": response
        })
    
    st.rerun()

# Example prompts at the bottom
with st.expander("📝 Example prompts"):
    st.code(
        "We've had 20 customers asking for dark mode.\n"
        "Users keep reporting sign-out fails after refresh.\n"
        "Customer feedback: 'The checkout flow feels confusing and slow.'\n"
        "Should we prioritize the payment flow over the onboarding?",
        language="text",
    )
