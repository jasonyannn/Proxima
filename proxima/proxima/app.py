import streamlit as st

try:
    from .agent import ProximaAgent
    from .database import DatabaseManager
    from .prompt import SYSTEM_PROMPT
except ImportError:  # pragma: no cover
    from agent import ProximaAgent
    from database import DatabaseManager
    from prompt import SYSTEM_PROMPT


@st.cache_resource
def get_agent() -> ProximaAgent:
    db = DatabaseManager()
    db.init_db()
    return ProximaAgent(database=db, system_prompt=SYSTEM_PROMPT)


st.set_page_config(
    page_title="Proxima PM Agent",
    page_icon="🤖",
    layout="centered",
)

st.title("🤖 PRODUCT MANAGEMENT AGENT")
st.caption("Turn customer feedback into structured product decisions.")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

with st.form("pm_form", clear_on_submit=True):
    user_input = st.text_area(
        "What would you like to do?",
        height=120,
        placeholder="Customers keep asking for dark mode...",
    )
    submitted = st.form_submit_button("Send")

if submitted and user_input.strip():
    agent = get_agent()
    response = agent.generate_response(user_input)
    st.session_state.chat_history.append({"user": user_input, "agent": response})

st.markdown("### Agent")

if not st.session_state.chat_history:
    st.info("Try: 'We've had 20 customers asking for dark mode.'")

for item in reversed(st.session_state.chat_history):
    st.markdown(f"**You:** {item['user']}")
    st.markdown(item['agent'])
    st.markdown("---")

st.markdown("### Example prompts")
st.code(
    "We've had 20 customers asking for dark mode.\n"
    "\n"
    "Users keep reporting sign-out fails after refresh.\n"
    "\n"
    "Customer feedback: 'The checkout flow feels confusing and slow.'",
    language="text",
)
