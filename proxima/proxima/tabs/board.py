# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jason Yan

"""Board tab.

Sprints and the tickets in them.
"""

from __future__ import annotations

import streamlit as st

try:
    from .. import theme
    from ..kanban import kanban
    from .constants import COLUMNS, LEVELS, SPRINT_STATES
except ImportError:  # pragma: no cover
    import theme
    from kanban import kanban
    from tabs.constants import COLUMNS, LEVELS, SPRINT_STATES


def render(*, db, get_agent, messages):
    """Draw the Board tab."""
    theme.section(
        "Board",
        note=(
            "Work, as opposed to what the product does — that lives in Features. "
            "A ticket can come from a feature you filed, from something you said "
            "in the chat, or from you typing it here."
        ),
        index="01",
    )

    sprints = db.list_sprints()
    sprint_names = {sprint["id"]: sprint["name"] for sprint in sprints}

    # --- sprint bar
    pick, make, _ = st.columns([3, 2, 2])
    view_options = ["Everything", "Backlog only"] + [s["name"] for s in sprints]
    view = pick.selectbox("Showing", view_options, label_visibility="collapsed")

    with make.popover("New sprint", use_container_width=True):
        with st.form("new_sprint", clear_on_submit=True):
            sprint_name = st.text_input("Name", placeholder=f"Sprint {len(sprints) + 1}")
            sprint_goal = st.text_area("Goal", height=70, placeholder="What this sprint is for")
            span = st.columns(2)
            starts = span[0].date_input("Starts", value=None, format="YYYY-MM-DD")
            ends = span[1].date_input("Ends", value=None, format="YYYY-MM-DD")
            if st.form_submit_button("Create sprint", type="primary"):
                name = sprint_name.strip() or f"Sprint {len(sprints) + 1}"
                db.create_sprint(
                    name=name,
                    goal=sprint_goal.strip() or None,
                    starts=str(starts) if starts else None,
                    ends=str(ends) if ends else None,
                )
                st.session_state.save_toast = f"{name} created."
                st.rerun()

    # --- what the board is showing
    if view == "Backlog only":
        tickets = [t for t in db.list_tickets() if t["sprint_id"] is None]
        active_sprint = None
    elif view == "Everything":
        tickets = db.list_tickets()
        active_sprint = None
    else:
        active_sprint = next((s for s in sprints if s["name"] == view), None)
        tickets = db.list_tickets(sprint_id=active_sprint["id"]) if active_sprint else []

    if active_sprint:
        with st.container(border=True):
            head, state_col, kill = st.columns([4, 2, 1])
            head.markdown(
                f"**{active_sprint['name']}** — {active_sprint.get('goal') or '_no goal set_'}"
            )
            dates = " → ".join(
                x for x in [active_sprint.get("starts"), active_sprint.get("ends")] if x
            )
            if dates:
                head.caption(dates)
            new_state = state_col.selectbox(
                "State",
                SPRINT_STATES,
                index=SPRINT_STATES.index(active_sprint.get("state") or "Planned"),
                key=f"sprint_state_{active_sprint['id']}",
                label_visibility="collapsed",
            )
            if new_state != (active_sprint.get("state") or "Planned"):
                db.update_sprint(active_sprint["id"], state=new_state)
                st.rerun()
            if kill.button("Delete", key=f"del_sprint_{active_sprint['id']}", use_container_width=True):
                db.delete_sprint(active_sprint["id"])
                st.session_state.save_toast = "Sprint deleted — its tickets went back to the backlog."
                st.rerun()

            done = [t for t in tickets if t["status"] == "Done"]
            if tickets:
                st.progress(len(done) / len(tickets), text=f"{len(done)} of {len(tickets)} done")

    # --- ways to get work onto the board
    add_col, scan_col, feat_col, _ = st.columns([2, 2, 2, 1])

    with add_col.popover("Add ticket", use_container_width=True):
        with st.form("new_ticket", clear_on_submit=True):
            ticket_title = st.text_input("Title")
            ticket_desc = st.text_area("Description", height=80)
            row = st.columns(3)
            ticket_priority = row[0].selectbox("Priority", LEVELS, index=1)
            ticket_status = row[1].selectbox("Column", COLUMNS)
            ticket_points = row[2].number_input("Estimate", min_value=0, max_value=21, value=0)
            ticket_sprint = st.selectbox(
                "Sprint", ["Backlog"] + [s["name"] for s in sprints]
            )
            if st.form_submit_button("Add", type="primary") and ticket_title.strip():
                target = next((s["id"] for s in sprints if s["name"] == ticket_sprint), None)
                db.create_ticket(
                    title=ticket_title.strip(),
                    description=ticket_desc.strip() or None,
                    status=ticket_status,
                    priority=ticket_priority,
                    estimate=int(ticket_points) or None,
                    sprint_id=target,
                    origin="typed",
                )
                st.session_state.save_toast = "Ticket added."
                st.rerun()

    if scan_col.button(
        "Suggest tickets from this chat",
        use_container_width=True,
        disabled=not messages,
        help="Reads the conversation for work it implies. Nothing is added until you say so.",
    ):
        with st.spinner("Reading the conversation…"):
            st.session_state.ticket_proposal = get_agent().suggest_tickets(messages)
        st.rerun()

    with feat_col.popover("From a feature", use_container_width=True):
        filed = db.list_features()
        if not filed:
            st.caption("Nothing filed in Features yet.")
        else:
            source = st.selectbox("Feature", [f["title"] for f in filed], key="ticket_from_feature")
            picked_feature = next(f for f in filed if f["title"] == source)
            if st.button("Create ticket", type="primary", key="make_ticket_from_feature"):
                db.create_ticket(
                    title=f"Build {picked_feature['title']}",
                    description=picked_feature.get("description") or None,
                    priority=str(picked_feature.get("priority") or "Medium").title(),
                    feature_id=picked_feature["id"],
                    origin="feature",
                )
                st.session_state.save_toast = f"Ticket created from {picked_feature['title']}."
                st.rerun()

    proposed_tickets = st.session_state.get("ticket_proposal")
    if proposed_tickets is not None:
        with st.container(border=True):
            if not proposed_tickets:
                st.caption("Nothing in this chat reads as work to be done yet.")
            else:
                st.markdown("**Work this chat implies.** Uncheck anything you disagree with.")
                keep = []
                for index, ticket in enumerate(proposed_tickets):
                    label = f"**{ticket['title']}** — {ticket['description']}"
                    if st.checkbox(label, value=True, key=f"tick_{index}_{ticket['title'][:20]}"):
                        keep.append(ticket)
                target_sprint = st.selectbox(
                    "Add to", ["Backlog"] + [s["name"] for s in sprints], key="ticket_target"
                )
                go, _ = st.columns([2, 3])
                if go.button(
                    f"Add {len(keep)} ticket{'s' if len(keep) != 1 else ''}",
                    type="primary",
                    use_container_width=True,
                    disabled=not keep,
                ):
                    target = next((s["id"] for s in sprints if s["name"] == target_sprint), None)
                    for ticket in keep:
                        db.create_ticket(
                            title=ticket["title"],
                            description=ticket["description"] or None,
                            priority=ticket["priority"],
                            sprint_id=target,
                            origin="chat",
                        )
                    st.session_state.pop("ticket_proposal", None)
                    st.session_state.save_toast = f"Added {len(keep)} tickets."
                    st.rerun()
            if st.button("Close", key="ticket_close"):
                st.session_state.pop("ticket_proposal", None)
                st.rerun()

    st.divider()

    # --- the board itself
    if not tickets:
        theme.empty_state(
            label="Board empty",
            title="No tickets here yet",
            body=(
                "Add one by hand, pull the work out of your chat, or turn a filed "
                "feature into a ticket. Sprints are optional — the backlog works "
                "on its own."
            ),
        )
    else:
        # The lanes are a component (see kanban.py) because dragging a card
        # from one column to another is not something Streamlit can observe.
        action = kanban(
            columns=COLUMNS,
            tickets=[
                {
                    "id": ticket["id"],
                    "title": ticket["title"],
                    "description": (ticket.get("description") or "")[:160],
                    "status": ticket.get("status") or COLUMNS[0],
                    "priority": ticket.get("priority") or "Medium",
                    "estimate": ticket.get("estimate"),
                    "sprint": sprint_names.get(ticket.get("sprint_id")),
                    "origin": ticket.get("origin"),
                }
                for ticket in tickets
            ],
            show_sprint=view == "Everything",
        )

        if isinstance(action, dict) and action.get("nonce") != st.session_state.get("board_nonce"):
            st.session_state.board_nonce = action["nonce"]
            if action.get("kind") == "move" and action.get("status") in COLUMNS:
                db.update_ticket(int(action["id"]), status=action["status"])
            elif action.get("kind") == "delete":
                db.delete_ticket(int(action["id"]))
            st.rerun()
