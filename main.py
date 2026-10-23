"""Streamlit UI for the customer-service chatbot and its operations console."""

from __future__ import annotations

from datetime import datetime, time

import streamlit as st

from src.chatbot import CustomerServiceChatbot
from src.config import settings
from src.knowledge_base import KnowledgeBaseManager
from src.monitoring import dashboard_summary, health_check
from src.security import authenticate, require_admin
from src.storage import init_database, list_versions, recent_audit
from src.update_pipeline import UpdatePipeline
from src.scheduler import UpdateScheduler


st.set_page_config(page_title="Customer Service Chatbot", page_icon="🤖", layout="wide")
init_database()

if "user" not in st.session_state:
    st.session_state.user = None


@st.cache_resource
def get_services():
    return UpdatePipeline(), CustomerServiceChatbot(), UpdateScheduler()


pipeline, chatbot, scheduler = get_services()
kb = pipeline.kb


def maintenance_demo_time() -> datetime:
    start_h, start_m = map(int, settings.maintenance_start.split(":"))
    return datetime.now().replace(hour=start_h, minute=start_m, second=0, microsecond=0)


st.title("🤖 Customer Service Chatbot")
st.caption("FAQ-based RAG assistant with a production-style knowledge-base update pipeline")

with st.sidebar:
    st.header("Access")
    if st.session_state.user:
        st.success(f"Signed in as {st.session_state.user.username} ({st.session_state.user.role})")
        if st.button("Sign out", use_container_width=True):
            st.session_state.user = None
            st.rerun()
    else:
        username = st.text_input("Username", value="user")
        password = st.text_input("Password", type="password", value="user")
        if st.button("Sign in", use_container_width=True):
            user = authenticate(username, password, settings.admin_username, settings.admin_password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Invalid username or password.")

    st.divider()
    active = kb.active_version()
    if active:
        st.success(f"Active KB: {active}")
    else:
        st.info("No active knowledge base yet.")

chat_tab, admin_tab, monitor_tab = st.tabs(["💬 Chat", "🛠️ Knowledge Base", "📊 Monitoring"])

with chat_tab:
    question = st.text_input(
        "Ask your question",
        placeholder="e.g. Do you provide any virtual internship?",
        key="chat_question",
    )
    if question.strip():
        with st.spinner("Finding the best FAQ answer..."):
            try:
                result = chatbot.answer(question.strip())
                st.subheader("Answer")
                st.write(result["answer"])
                st.caption(f"Confidence: {result['score']:.3f}")
                if result.get("escalated"):
                    st.info("This request was safely handled or marked for escalation.")
                if result.get("source_question"):
                    with st.expander("Retrieved FAQ"):
                        st.write("**Question:**", result["source_question"])
            except Exception as exc:
                st.error(f"Could not answer the question: {exc}")

with admin_tab:
    st.subheader("Knowledge-base operations")
    user = st.session_state.user
    if not user:
        st.info("Sign in as an administrator to manage knowledge-base updates.")
    else:
        try:
            require_admin(user)
        except PermissionError as exc:
            st.warning(str(exc))
        else:
            st.write(
                "The pipeline scans for new/modified files, removes duplicates, quarantines "
                "invalid files, runs quality gates, and activates only inside the maintenance window."
            )

            uploaded = st.file_uploader(
                "Add a new knowledge-base document",
                type=["csv", "txt", "md", "json"],
                help="Files are staged in knowledge_base/incoming/ and are not activated automatically.",
            )
            if uploaded is not None and st.button("Save document for next update"):
                target = settings.incoming_dir / uploaded.name
                target.write_bytes(uploaded.getbuffer())
                st.success(f"Saved {uploaded.name}. Run the scan and quality-gate steps next.")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔎 Scan documents", use_container_width=True):
                    scan = pipeline.scan()
                    st.write(f"Accepted: **{len(scan['accepted'])}**")
                    st.write(f"Duplicates: **{len(scan['duplicates'])}**")
                    st.write(f"Quarantined: **{len(scan['quarantined'])}**")
                    if scan["duplicates"]:
                        st.dataframe([r.__dict__ for r in scan["duplicates"]], use_container_width=True)
                    if scan["quarantined"]:
                        st.dataframe([r.__dict__ for r in scan["quarantined"]], use_container_width=True)

            with col2:
                if st.button("🚀 Stage + test update", use_container_width=True):
                    try:
                        result = pipeline.stage_candidate()
                        if result["status"] == "unchanged":
                            st.info("No new or modified documents detected.")
                        else:
                            quality = pipeline.quality_gate(result["version_id"])
                            if quality["passed"]:
                                st.success(f"Candidate {result['version_id']} passed quality checks.")
                            else:
                                st.error("Candidate rejected because quality/grounding regressed.")
                            st.json(
                                {
                                    "version": result.get("version_id"),
                                    "duplicates": len(result["duplicates"]),
                                    "quarantined": len(result["quarantined"]),
                                    "quality_passed": quality["passed"],
                                }
                            )
                    except Exception as exc:
                        st.error(f"Update failed safely: {exc}")

            st.divider()
            st.subheader("Activation")
            simulate_window = st.checkbox(
                "Simulate maintenance window (for testing/demo)",
                help="Uses the configured maintenance-window start time without waiting for the clock.",
            )
            candidate_versions = [
                row["version_id"] for row in list_versions()
                if row["status"] in {"approved", "candidate"}
            ]
            selected = st.selectbox("Candidate version", candidate_versions or ["No candidate available"])
            if st.button("✅ Activate approved version", use_container_width=True):
                if selected == "No candidate available":
                    st.warning("Stage an update first.")
                else:
                    try:
                        now = maintenance_demo_time() if simulate_window else datetime.now()
                        result = pipeline.activate(selected, now=now, health_ok=True, user=user)
                        st.write(result)
                    except Exception as exc:
                        st.error(str(exc))

            st.divider()
            st.subheader("Rollback")
            versions = [row["version_id"] for row in list_versions()]
            rollback_target = st.selectbox("Rollback target", versions or ["No versions"])
            if st.button("↩️ Roll back", use_container_width=True):
                if rollback_target != "No versions":
                    try:
                        st.success(f"Rolled back to {pipeline.rollback(rollback_target, 'Admin requested rollback', user=user)}")
                    except Exception as exc:
                        st.error(str(exc))

            st.divider()
            st.subheader("Scheduling")
            run_at = st.time_input("Scheduled update time", value=time.fromisoformat(settings.scheduled_update_time))
            if st.button("🕒 Schedule update", use_container_width=True):
                now = datetime.now().replace(hour=run_at.hour, minute=run_at.minute, second=0, microsecond=0)
                job_id = scheduler.schedule_for(now)
                st.success(f"Scheduled job: {job_id}")
            st.caption(f"Automatic retries: {', '.join(map(str, settings.retry_delays))} minutes after failures.")

with monitor_tab:
    st.subheader("Operational health")
    summary = dashboard_summary()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Requests", summary["requests"])
    c2.metric("Failures", summary["failures"])
    c3.metric("Escalations", summary["escalations"])
    c4.metric("Avg latency", f"{summary['average_latency_ms']:.0f} ms")
    c5.metric("Avg confidence", f"{summary['average_confidence']:.2f}")

    if st.button("Run health check"):
        result = health_check(chatbot)
        if result["healthy"]:
            st.success(f"Healthy — {result['latency_ms']} ms")
        else:
            st.error(f"Unhealthy — {result['reason']}")

    with st.expander("Version history"):
        st.dataframe(list_versions(), use_container_width=True)

    with st.expander("Audit log"):
        st.dataframe(recent_audit(), use_container_width=True)
