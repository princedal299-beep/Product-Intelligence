import os
import uuid
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="Product Intelligence Chatbot",
    page_icon="🤖",
    layout="wide",
)
st.title("🤖 Product Intelligence Chatbot")

st.markdown(
    """
    <style>
    .stChatMessage img {
        max-width: 300px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
        margin: 10px 0;
        display: block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def api_error(response):
    try:
        body = response.json()
    except ValueError:
        return f"Request failed ({response.status_code})."
    return str(body.get("detail", f"Request failed ({response.status_code})."))


def api_request(method, endpoint, headers=None, params=None, data=None, body=None, stream=False):
    try:
        return requests.request(
            method,
            f"{API_BASE_URL}/{endpoint.lstrip('/')}",
            timeout=500,
            headers=headers,
            params=params,
            data=data,
            json=body,
            stream=stream,
        )
    except requests.RequestException as exc:
        st.error(f"Could not reach the API: {exc}")
        return None


def save_login(response):
    response.raise_for_status()
    account = response.json()
    token = account["access_token"]
    st.session_state["access_token"] = token
    st.session_state["role"] = account["role"]
    st.session_state["email"] = account["email"]
    st.session_state["user_id"] = str(account["user_id"])
    st.session_state["messages"] = []
    st.query_params["token"] = token


@st.fragment(run_every=2)
def render_catalog_reindexing(headers):
    status_resp = api_request("GET", "admin/reindex/status", headers=headers)
    s_info = {}
    curr_status = "idle"
    if status_resp is not None and status_resp.ok:
        s_info = status_resp.json()
        curr_status = s_info.get("status", "idle")
    elif status_resp is not None and status_resp.status_code == 401:
        st.error("Session expired. Please log out and log in again.")
        return

    is_running = (curr_status == "running")
    st.session_state["reindex_running"] = is_running

    if st.button("Start Reindexing", disabled=is_running):
        reindex_resp = api_request("POST", "admin/reindex", headers=headers)
        if reindex_resp is not None and reindex_resp.status_code in (200, 202):
            st.session_state["reindex_running"] = True
            st.rerun()
        elif reindex_resp is not None and reindex_resp.status_code == 409:
            st.session_state["reindex_running"] = True
            st.warning("Reindexing is already in progress.")
            st.rerun()
        elif reindex_resp is not None and reindex_resp.status_code == 401:
            st.error("Session expired. Please log out and log in again.")
        else:
            st.error(api_error(reindex_resp) if reindex_resp else "Request failed.")

    if curr_status == "running":
        processed = int(s_info.get("processed", 0))
        total = int(s_info.get("total", 0))
        remaining = max(0, total - processed)
        fraction = min(1.0, max(0.0, processed / total)) if total > 0 else 0.0
        pct = int(fraction * 100)
        bar_text = (
            f"{pct}% completed - {processed:,} / {total:,} done ({remaining:,} remaining)"
            if total > 0
            else "Indexing catalog products..."
        )
        st.progress(fraction, text=bar_text)
        st.caption(f"⏳ In Progress — Started: {s_info.get('started_at', '')[:19]}")

    elif curr_status == "completed":
        summary = s_info.get("summary") or {}
        total = s_info.get("total") or summary.get("rows_loaded", 0)
        st.progress(1.0, text=f"100% completed - {total:,} / {total:,} done (0 remaining)")
        st.success(
            f"✅ Reindexing completed at {s_info.get('completed_at', '')[:19]}\n\n"
            f"• Loaded: {summary.get('rows_loaded', 0):,}\n"
            f"• Rejected: {summary.get('rows_rejected', 0):,}\n"
            f"• Duplicates: {summary.get('duplicates_removed', 0):,}"
        )

    elif curr_status == "failed":
        st.error(f"❌ Reindexing failed: {s_info.get('error', 'Unknown error')}")

    else:
        st.write("Status: Idle (No active reindexing)")


if "access_token" not in st.session_state:
    stored_token = st.query_params.get("token")
    if stored_token:
        response = api_request(
            "GET",
            "me",
            headers={"Authorization": f"Bearer {stored_token}"},
        )
        if response is not None and response.ok:
            account = response.json()
            st.session_state["access_token"] = stored_token
            st.session_state["role"] = account["role"]
            st.session_state["email"] = account["email"]
            st.session_state["user_id"] = str(account["user_id"])
            if "messages" not in st.session_state:
                st.session_state["messages"] = []
        else:
            st.query_params.clear()
            st.warning("Your session has expired. Please log in again.")

if "access_token" not in st.session_state:
    login_tab, register_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            login_submitted = st.form_submit_button("Log in")
            if login_submitted:
                response = api_request(
                    "POST",
                    "Login",
                    data={"username": email, "password": password},
                )
                if response is not None:
                    if response.ok:
                        save_login(response)
                        st.rerun()
                    st.error(api_error(response))

    with register_tab:
        with st.form("register_form"):
            new_email = st.text_input("Email", key="register_email")
            new_password = st.text_input(
                "Password (at least 8 characters)",
                type="password",
                key="register_password",
            )
            register_submitted = st.form_submit_button("Create Shopper account")
            if register_submitted:
                response = api_request(
                    "POST",
                    "register",
                    body={"email": new_email, "password": new_password},
                )
                if response is not None:
                    if response.status_code == 201:
                        st.success("Account created. Log in to continue.")
                    else:
                        st.error(api_error(response))
    st.stop()


token = st.session_state["access_token"]
role = st.session_state["role"]
headers = {"Authorization": f"Bearer {token}"}

with st.sidebar:
    st.write(f"Signed in as: **{st.session_state['email']}**")
    st.write(f"Role: **`{role}`**")
    if st.button("Log out"):
        st.query_params.clear()
        for key in (
            "access_token",
            "role",
            "email",
            "user_id",
            "messages",
            "admin_user",
            "audit_offset",
            "audit_logs",
        ):
            st.session_state.pop(key, None)
        st.rerun()

    if role == "ADMIN":
        st.divider()
        st.subheader("Admin Controls")

        with st.expander("Manage User Roles", expanded=False):
            with st.form("find_user_form"):
                lookup_email = st.text_input("User Email")
                find_submitted = st.form_submit_button("Find user")
            if find_submitted:
                clean_email = lookup_email.strip() if lookup_email else ""
                if not clean_email:
                    st.warning("Please enter an email address.")
                else:
                    response = api_request(
                        "GET",
                        "admin/users",
                        params={"email": clean_email},
                        headers=headers,
                    )
                    if response is not None:
                        if response.ok:
                            st.session_state["admin_user"] = response.json()
                        else:
                            st.session_state.pop("admin_user", None)
                            st.error(api_error(response))

            target_user = st.session_state.get("admin_user")
            if target_user:
                st.write(f"Email: **{target_user['email']}**")
                current_role = target_user.get("role", "Shopper")
                roles = ["Shopper", "Merchandiser"]
                role_idx = roles.index(current_role) if current_role in roles else 0

                with st.form("update_role_form"):
                    selected_role = st.selectbox(
                        "Role",
                        roles,
                        index=role_idx,
                    )
                    save_submitted = st.form_submit_button("Save role")

                if save_submitted:
                    response = api_request(
                        "PATCH",
                        f"admin/users/{target_user['id']}/role",
                        body={"role": selected_role},
                        headers=headers,
                    )
                    if response is not None:
                        if response.ok:
                            updated_user = response.json()
                            st.session_state["admin_user"] = updated_user
                            if str(st.session_state.get("user_id")) == str(target_user.get("id")):
                                st.session_state["role"] = updated_user["role"]
                            st.success(f"Role updated to {updated_user['role']} successfully.")
                            st.rerun()
                        else:
                            st.error(api_error(response))

        with st.expander("Catalog Reindexing", expanded=st.session_state.get("reindex_running", False)):
            render_catalog_reindexing(headers)

        with st.expander("View Audit Logs", expanded=False):
            if "audit_offset" not in st.session_state:
                st.session_state["audit_offset"] = 0
            if "audit_logs" not in st.session_state:
                st.session_state["audit_logs"] = None

            if st.button("Refresh Logs", key="refresh_audit_logs"):
                st.session_state["audit_offset"] = 0
                audit_resp = api_request(
                    "GET",
                    "admin/audit",
                    params={"limit": 50, "offset": 0},
                    headers=headers,
                )
                if audit_resp is not None and audit_resp.ok:
                    st.session_state["audit_logs"] = audit_resp.json()
                else:
                    st.session_state["audit_logs"] = None
                    st.error("Could not fetch audit logs.")

            if st.session_state.get("audit_logs") is None:
                audit_resp = api_request(
                    "GET",
                    "admin/audit",
                    params={"limit": 50, "offset": st.session_state["audit_offset"]},
                    headers=headers,
                )
                if audit_resp is not None and audit_resp.ok:
                    st.session_state["audit_logs"] = audit_resp.json()
                else:
                    st.session_state["audit_logs"] = []

            logs = st.session_state.get("audit_logs")
            if logs is not None:
                offset = st.session_state["audit_offset"]
                if logs:
                    st.caption(f"Showing audits {offset + 1} - {offset + len(logs)}")
                    for log in logs:
                        agent_display = log.get("agent") or log.get("route") or "catalog_agent"
                        st.text(
                            f"[{log.get('timestamp', '')[:19]}] [{agent_display}] {log.get('role')} "
                            f"(user: {log.get('user_id')}): {log.get('query')}"
                        )
                else:
                    st.info("No audit logs found.")

                col_prev, col_next = st.columns(2)
                with col_prev:
                    if st.button("Previous", key="prev_audit_logs", disabled=(offset <= 0)):
                        new_offset = max(0, offset - 50)
                        resp = api_request(
                            "GET",
                            "admin/audit",
                            params={"limit": 50, "offset": new_offset},
                            headers=headers,
                        )
                        if resp is not None and resp.ok:
                            st.session_state["audit_offset"] = new_offset
                            st.session_state["audit_logs"] = resp.json()
                            st.rerun()
                        else:
                            st.error("Could not fetch previous audit logs.")

                with col_next:
                    if st.button("Next", key="next_audit_logs", disabled=(len(logs) < 50)):
                        new_offset = offset + 50
                        resp = api_request(
                            "GET",
                            "admin/audit",
                            params={"limit": 50, "offset": new_offset},
                            headers=headers,
                        )
                        if resp is not None and resp.ok:
                            st.session_state["audit_offset"] = new_offset
                            st.session_state["audit_logs"] = resp.json()
                            st.rerun()
                        else:
                            st.error("Could not fetch next audit logs.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"], unsafe_allow_html=False)

prompt = st.chat_input("Type your question about products ...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching catalog and verifying answer..."):
            user_id = st.session_state.get("user_id", "anon")
            session_id = st.session_state.setdefault("session_id", uuid.uuid4().hex[:8])
            response = api_request(
                "POST",
                "chat",
                headers=headers,
                body={
                    "query": prompt,
                    "thread_id": session_id,
                    "stream": True,
                },
                stream=True,
            )

        if response is None:
            bot_reply = "Could not connect to the Product Intelligence API service."
            st.markdown(bot_reply)
        elif response.status_code == 403:
            bot_reply = "Catalog analytics and numerical metrics are available to merchandisers and admins only."
            st.markdown(bot_reply)
        elif response.status_code == 429:
            bot_reply = "Rate limit reached. Please wait a moment before sending another request."
            st.markdown(bot_reply)
        elif response.ok:
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                data = response.json()
                bot_reply = data.get("answer", "")
                st.markdown(bot_reply, unsafe_allow_html=False)
            else:
                def stream_chunks():
                    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                        if chunk:
                            yield chunk
                bot_reply = st.write_stream(stream_chunks())
        else:
            bot_reply = api_error(response)
            st.markdown(bot_reply)

    st.session_state.messages.append({"role": "assistant", "content": bot_reply})
