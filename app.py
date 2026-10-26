import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

APP_NAME = "DentalFlow"
DB_PATH = os.getenv("DENTALFLOW_DB_PATH", "dentalflow.db")

st.set_page_config(
    page_title="DentalFlow | Lab Work Orders",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

STATUSES = [
    "Received",
    "Accepted",
    "In Production",
    "Quality Check",
    "Ready for Dispatch",
    "Dispatched",
    "Delivered",
    "On Hold",
    "Cancelled",
]
ACTIVE_STATUSES = ["Received", "Accepted", "In Production", "Quality Check", "Ready for Dispatch", "Dispatched", "On Hold"]
CASE_TYPES = [
    "Zirconia Crown",
    "PFM Crown",
    "E.max Crown",
    "Bridge",
    "Implant Crown",
    "Denture",
    "Veneer",
    "Night Guard",
    "Aligner / Retainer",
    "Other",
]
PRIORITIES = ["Routine", "Priority", "Urgent"]


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                dentist_name TEXT NOT NULL,
                clinic_name TEXT NOT NULL,
                dentist_email TEXT NOT NULL,
                patient_ref TEXT NOT NULL,
                case_type TEXT NOT NULL,
                tooth_numbers TEXT,
                shade TEXT,
                material TEXT,
                units INTEGER NOT NULL DEFAULT 1,
                priority TEXT NOT NULL DEFAULT 'Routine',
                due_date TEXT NOT NULL,
                instructions TEXT,
                status TEXT NOT NULL DEFAULT 'Received',
                lab_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                changed_by TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if count == 0:
            now = datetime.now()
            samples = [
                ("DF-1048", "Dr. Maya Rao", "Indiranagar Dental Care", "maya@example.com", "PT-2031", "Zirconia Crown", "16", "A2", "Monolithic zirconia", 1, "Priority", (date.today() + timedelta(days=2)).isoformat(), "Match adjacent tooth; contact clinic if shade confirmation needed.", "In Production", "Framework completed; contouring in progress.", now - timedelta(days=3)),
                ("DF-1047", "Dr. Arjun Mehta", "WhiteArc Dental Studio", "arjun@example.com", "PT-1984", "E.max Crown", "11", "A1", "Lithium disilicate", 1, "Routine", (date.today() + timedelta(days=4)).isoformat(), "High translucency, natural incisal edge.", "Accepted", "", now - timedelta(days=2)),
                ("DF-1046", "Dr. Maya Rao", "Indiranagar Dental Care", "maya@example.com", "PT-2027", "Bridge", "24-26", "A3", "Zirconia", 3, "Urgent", (date.today() + timedelta(days=1)).isoformat(), "Please prioritize; verify pontic contour.", "Quality Check", "Final fit check underway.", now - timedelta(days=4)),
                ("DF-1045", "Dr. Neha Iyer", "SmileCraft Clinic", "neha@example.com", "PT-1872", "Night Guard", "Full arch", "Clear", "Hard-soft splint", 1, "Routine", (date.today() - timedelta(days=1)).isoformat(), "Upper arch, light occlusal adjustment.", "Ready for Dispatch", "Packed and awaiting courier pickup.", now - timedelta(days=5)),
                ("DF-1044", "Dr. Arjun Mehta", "WhiteArc Dental Studio", "arjun@example.com", "PT-1855", "Veneer", "21", "B1", "E.max", 1, "Routine", (date.today() - timedelta(days=2)).isoformat(), "Keep preparation margins conservative.", "Delivered", "Delivered to clinic reception.", now - timedelta(days=8)),
            ]
            for row in samples:
                (oid, dentist, clinic, email, patient, case, teeth, shade, material, units,
                 priority, due, instructions, status, notes, created) = row
                created_s = created.isoformat(timespec="minutes")
                updated_s = now.isoformat(timespec="minutes")
                conn.execute(
                    """INSERT INTO orders
                    (id,dentist_name,clinic_name,dentist_email,patient_ref,case_type,tooth_numbers,
                     shade,material,units,priority,due_date,instructions,status,lab_notes,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (oid, dentist, clinic, email, patient, case, teeth, shade, material, units,
                     priority, due, instructions, status, notes, created_s, updated_s),
                )
                conn.execute(
                    "INSERT INTO order_history (order_id,status,note,changed_by,changed_at) VALUES (?,?,?,?,?)",
                    (oid, "Received", "Order submitted to the lab.", dentist, created_s),
                )
                if status != "Received":
                    conn.execute(
                        "INSERT INTO order_history (order_id,status,note,changed_by,changed_at) VALUES (?,?,?,?,?)",
                        (oid, status, notes or f"Status updated to {status}.", "Lab team", updated_s),
                    )


def load_orders():
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM orders ORDER BY created_at DESC", conn)


def load_history(order_id):
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT status,note,changed_by,changed_at FROM order_history WHERE order_id=? ORDER BY changed_at DESC, id DESC",
            conn, params=(order_id,)
        )


def create_order(data):
    now = datetime.now().isoformat(timespec="minutes")
    order_id = "DF-" + uuid.uuid4().hex[:6].upper()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO orders
            (id,dentist_name,clinic_name,dentist_email,patient_ref,case_type,tooth_numbers,
             shade,material,units,priority,due_date,instructions,status,lab_notes,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order_id, data["dentist_name"].strip(), data["clinic_name"].strip(),
                data["dentist_email"].strip(), data["patient_ref"].strip(), data["case_type"],
                data["tooth_numbers"].strip(), data["shade"].strip(), data["material"].strip(),
                data["units"], data["priority"], data["due_date"].isoformat(),
                data["instructions"].strip(), "Received", "", now, now,
            ),
        )
        conn.execute(
            "INSERT INTO order_history (order_id,status,note,changed_by,changed_at) VALUES (?,?,?,?,?)",
            (order_id, "Received", "New order submitted.", data["dentist_name"].strip(), now),
        )
    return order_id


def update_order(order_id, status, notes, changed_by="Lab team"):
    now = datetime.now().isoformat(timespec="minutes")
    with get_conn() as conn:
        current = conn.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        if not current:
            raise ValueError("Order not found.")
        conn.execute(
            "UPDATE orders SET status=?, lab_notes=?, updated_at=? WHERE id=?",
            (status, notes.strip(), now, order_id),
        )
        if current["status"] != status or notes.strip():
            note = notes.strip() or f"Status changed to {status}."
            conn.execute(
                "INSERT INTO order_history (order_id,status,note,changed_by,changed_at) VALUES (?,?,?,?,?)",
                (order_id, status, note, changed_by, now),
            )


def inject_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
        :root { --ink:#172B4D; --muted:#718096; --teal:#087E8B; --teal-dark:#06636D;
                --line:#E5EBF2; --canvas:#F5F8FC; --white:#FFFFFF; }
        html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
        .stApp { background:var(--canvas); color:var(--ink); }
        [data-testid="stHeader"] { background:rgba(245,248,252,.92); }
        [data-testid="stSidebar"] { background:#FFFFFF; border-right:1px solid var(--line); }
        [data-testid="stSidebar"] > div { padding-top:1.25rem; }
        h1,h2,h3 { font-family:'Manrope',sans-serif !important; color:var(--ink); letter-spacing:-.035em; }
        h1 { font-size:2rem !important; font-weight:800 !important; }
        h2 { font-size:1.35rem !important; font-weight:750 !important; }
        .brand { font-family:'Manrope',sans-serif; font-size:1.45rem; font-weight:800; color:var(--ink); }
        .brand span { color:var(--teal); }
        .eyebrow { text-transform:uppercase; letter-spacing:.13em; font-size:.69rem; font-weight:700; color:var(--teal); }
        .page-subtitle { color:var(--muted); margin-top:-.55rem; margin-bottom:1.25rem; }
        .metric-card { background:#fff; border:1px solid var(--line); border-radius:16px; padding:18px 19px; min-height:118px; box-shadow:0 3px 12px rgba(27,48,76,.025); }
        .metric-label { color:#718096; font-size:.82rem; font-weight:600; }
        .metric-value { color:var(--ink); font-family:'Manrope',sans-serif; font-size:1.9rem; font-weight:800; line-height:1.55; }
        .metric-foot { font-size:.75rem; color:#7D8BA0; }
        .section-card { background:#fff; border:1px solid var(--line); border-radius:16px; padding:20px; margin-bottom:14px; }
        .case-id { color:var(--teal); font-weight:800; letter-spacing:.02em; }
        .muted { color:var(--muted); font-size:.88rem; }
        .pill { display:inline-block; border-radius:999px; padding:4px 10px; font-size:.72rem; font-weight:700; background:#E6F5F5; color:#087E8B; }
        .stButton > button, .stFormSubmitButton > button { border-radius:10px; font-weight:700; min-height:2.65rem; border:1px solid #D9E3EE; }
        .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] { background:var(--teal); border-color:var(--teal); color:white; }
        .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover { background:var(--teal-dark); border-color:var(--teal-dark); }
        div[data-baseweb="input"] input, div[data-baseweb="select"] > div, textarea { border-radius:9px !important; }
        div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
        div[data-testid="stExpander"] { background:white; border:1px solid var(--line); border-radius:12px; }
        hr { border-color:var(--line); }
        .footer-note { color:#8A97A9; font-size:.76rem; text-align:center; padding:20px 0 8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def metric(label, value, foot):
    st.markdown(
        f"""<div class="metric-card"><div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div><div class="metric-foot">{foot}</div></div>""",
        unsafe_allow_html=True,
    )


def status_label(status):
    icons = {
        "Received": "📥", "Accepted": "✓", "In Production": "⚙️",
        "Quality Check": "🔎", "Ready for Dispatch": "📦", "Dispatched": "🚚",
        "Delivered": "✓", "On Hold": "⏸", "Cancelled": "✕",
    }
    return f'{icons.get(status, "•")} {status}'


def render_order_table(df):
    if df.empty:
        st.info("No orders match your filters.")
        return
    view = df.copy()
    view["Order"] = view["id"]
    view["Patient ref"] = view["patient_ref"]
    view["Case"] = view["case_type"]
    view["Due date"] = view["due_date"]
    view["Status"] = view["status"]
    view["Priority"] = view["priority"]
    cols = ["Order", "Patient ref", "Case", "Due date", "Status", "Priority"]
    st.dataframe(view[cols], use_container_width=True, hide_index=True)


def render_order_details(order):
    with st.expander(f'{order["id"]} · {order["case_type"]} · {order["status"]}', expanded=False):
        left, right = st.columns(2)
        with left:
            st.markdown(f'**Clinic:** {order["clinic_name"]}')
            st.markdown(f'**Dentist:** {order["dentist_name"]}')
            st.markdown(f'**Patient reference:** {order["patient_ref"]}')
            st.markdown(f'**Teeth / area:** {order["tooth_numbers"] or "—"}')
            st.markdown(f'**Shade:** {order["shade"] or "—"}')
        with right:
            st.markdown(f'**Material:** {order["material"] or "—"}')
            st.markdown(f'**Units:** {order["units"]}')
            st.markdown(f'**Priority:** {order["priority"]}')
            st.markdown(f'**Due:** {order["due_date"]}')
            st.markdown(f'**Submitted:** {order["created_at"]}')
        if order["instructions"]:
            st.markdown("**Dentist instructions**")
            st.write(order["instructions"])
        if order["lab_notes"]:
            st.markdown("**Latest lab note**")
            st.write(order["lab_notes"])
        hist = load_history(order["id"])
        st.markdown("**Order timeline**")
        if hist.empty:
            st.caption("No timeline events yet.")
        else:
            for _, event in hist.iterrows():
                st.markdown(
                    f'**{event["status"]}** · {event["changed_at"]}  \n'
                    f'{event["note"] or ""}  \n'
                    f'<span class="muted">Updated by {event["changed_by"]}</span>',
                    unsafe_allow_html=True,
                )
                st.divider()


def dentist_portal(df):
    st.markdown('<div class="eyebrow">DENTIST WORKSPACE</div>', unsafe_allow_html=True)
    st.title("Your lab orders")
    st.markdown('<div class="page-subtitle">Submit cases, follow progress, and keep every case in one place.</div>', unsafe_allow_html=True)

    mine_name = st.session_state.get("dentist_name", "Dr. Maya Rao")
    mine_clinic = st.session_state.get("clinic_name", "Indiranagar Dental Care")
    mine_email = st.session_state.get("dentist_email", "maya@example.com")

    active = df[~df["status"].isin(["Delivered", "Cancelled"])] if not df.empty else df
    completed = df[df["status"] == "Delivered"] if not df.empty else df
    c1, c2, c3 = st.columns(3)
    with c1: metric("Active cases", len(active), "Cases still in progress")
    with c2: metric("Ready for dispatch", int((df["status"] == "Ready for Dispatch").sum()) if not df.empty else 0, "Awaiting collection")
    with c3: metric("Delivered cases", len(completed), "Completed and delivered")

    tab_new, tab_orders, tab_history = st.tabs(["＋  New work order", "▤  My orders", "◷  Order history"])
    with tab_new:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("Create a lab order")
        st.caption("Fields marked * are required. Use a patient reference instead of a full patient name in this demo.")
        with st.form("new_order_form", clear_on_submit=True):
            st.markdown("**Clinic details**")
            a, b = st.columns(2)
            with a:
                dentist_name = st.text_input("Dentist name *", value=mine_name)
                clinic_name = st.text_input("Clinic name *", value=mine_clinic)
            with b:
                dentist_email = st.text_input("Contact email *", value=mine_email)
                patient_ref = st.text_input("Patient reference / case code *", placeholder="e.g. PT-2048")
            st.divider()
            st.markdown("**Case specifications**")
            a, b, c = st.columns(3)
            with a:
                case_type = st.selectbox("Case type *", CASE_TYPES)
                tooth_numbers = st.text_input("Tooth number(s) / area", placeholder="e.g. 11, 12 or upper arch")
            with b:
                shade = st.text_input("Shade", placeholder="e.g. A2")
                material = st.text_input("Material", placeholder="e.g. Monolithic zirconia")
            with c:
                units = st.number_input("Number of units", min_value=1, max_value=32, value=1)
                priority = st.selectbox("Priority", PRIORITIES)
            a, b = st.columns(2)
            with a:
                due_date = st.date_input("Requested due date *", value=date.today() + timedelta(days=5), min_value=date.today())
            with b:
                instructions = st.text_area("Lab instructions", placeholder="Occlusion, contacts, margin notes, special requests…", height=100)
            submitted = st.form_submit_button("Submit work order", type="primary", use_container_width=True)
            if submitted:
                if not dentist_name.strip() or not clinic_name.strip() or not dentist_email.strip() or not patient_ref.strip():
                    st.error("Please complete all required fields.")
                elif "@" not in dentist_email:
                    st.error("Please enter a valid contact email.")
                else:
                    new_id = create_order({
                        "dentist_name": dentist_name, "clinic_name": clinic_name,
                        "dentist_email": dentist_email, "patient_ref": patient_ref,
                        "case_type": case_type, "tooth_numbers": tooth_numbers,
                        "shade": shade, "material": material, "units": int(units),
                        "priority": priority, "due_date": due_date, "instructions": instructions,
                    })
                    st.session_state["dentist_name"] = dentist_name
                    st.session_state["clinic_name"] = clinic_name
                    st.session_state["dentist_email"] = dentist_email
                    st.success(f"Order {new_id} submitted successfully.")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # Prototype filter: the demo profile can switch identity in the sidebar.
    current_email = st.session_state.get("dentist_email", "maya@example.com").strip().lower()
    my_df = df[df["dentist_email"].str.lower() == current_email] if not df.empty else df
    with tab_orders:
        a, b = st.columns([2, 1])
        with a:
            q = st.text_input("Search my orders", placeholder="Order ID, patient ref, case type…", key="dentist_search")
        with b:
            status_filter = st.selectbox("Status", ["All statuses"] + STATUSES, key="dentist_status")
        filtered = my_df.copy()
        if q:
            mask = filtered.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
            filtered = filtered[mask]
        if status_filter != "All statuses":
            filtered = filtered[filtered["status"] == status_filter]
        render_order_table(filtered)
        for _, order in filtered.iterrows():
            render_order_details(order)
    with tab_history:
        history_df = my_df[my_df["status"].isin(["Delivered", "Cancelled"])] if not my_df.empty else my_df
        st.caption("Delivered and cancelled cases are retained here for reference.")
        render_order_table(history_df)
        for _, order in history_df.iterrows():
            render_order_details(order)


def lab_dashboard(df):
    st.markdown('<div class="eyebrow">LAB OPERATIONS</div>', unsafe_allow_html=True)
    st.title("Lab dashboard")
    st.markdown('<div class="page-subtitle">A live view of incoming cases, production progress, and dispatch readiness.</div>', unsafe_allow_html=True)

    if df.empty:
        st.info("No orders yet. Orders submitted in the dentist portal will appear here.")
        return

    today = date.today().isoformat()
    open_df = df[~df["status"].isin(["Delivered", "Cancelled"])]
    overdue = open_df[open_df["due_date"] < today]
    received = df[df["status"] == "Received"]
    production = df[df["status"] == "In Production"]
    ready = df[df["status"] == "Ready for Dispatch"]

    cols = st.columns(4)
    with cols[0]: metric("Open cases", len(open_df), "Not yet delivered")
    with cols[1]: metric("New received", len(received), "Awaiting lab acceptance")
    with cols[2]: metric("In production", len(production), "Currently being fabricated")
    with cols[3]: metric("Overdue", len(overdue), "Open cases past due date")

    tab_queue, tab_manage, tab_all = st.tabs(["▤  Work queue", "⚙  Update a case", "▦  All orders"])
    with tab_queue:
        a, b, c = st.columns([1.3, 1, 1])
        with a:
            status_filter = st.selectbox("Status", ["All active"] + ACTIVE_STATUSES, key="lab_queue_status")
        with b:
            priority_filter = st.selectbox("Priority", ["All priorities"] + PRIORITIES, key="lab_queue_priority")
        with c:
            sort_by = st.selectbox("Sort by", ["Due date", "Newest first", "Priority"], key="lab_queue_sort")
        queue = open_df.copy()
        if status_filter != "All active":
            queue = queue[queue["status"] == status_filter]
        if priority_filter != "All priorities":
            queue = queue[queue["priority"] == priority_filter]
        if sort_by == "Due date":
            queue = queue.sort_values("due_date")
        elif sort_by == "Newest first":
            queue = queue.sort_values("created_at", ascending=False)
        else:
            queue["_rank"] = queue["priority"].map({"Urgent": 0, "Priority": 1, "Routine": 2})
            queue = queue.sort_values(["_rank", "due_date"])
        render_order_table(queue)
        for _, order in queue.iterrows():
            render_order_details(order)

    with tab_manage:
        ids = df["id"].tolist()
        chosen = st.selectbox("Select order", ids, format_func=lambda x: f'{x} · {df.loc[df["id"] == x, "case_type"].iloc[0]} · {df.loc[df["id"] == x, "patient_ref"].iloc[0]}')
        order = df[df["id"] == chosen].iloc[0]
        with st.container(border=True):
            a, b = st.columns(2)
            with a:
                st.markdown(f"### {order['id']}")
                st.write(f"**Clinic:** {order['clinic_name']}")
                st.write(f"**Case:** {order['case_type']} · {order['units']} unit(s)")
                st.write(f"**Patient reference:** {order['patient_ref']}")
            with b:
                st.write(f"**Current status:** {status_label(order['status'])}")
                st.write(f"**Due date:** {order['due_date']}")
                st.write(f"**Priority:** {order['priority']}")
                st.write(f"**Dentist:** {order['dentist_name']}")
            st.write("**Dentist instructions**")
            st.write(order["instructions"] or "No special instructions provided.")
        with st.form("update_order_form"):
            next_status = st.selectbox("Update status", STATUSES, index=STATUSES.index(order["status"]))
            notes = st.text_area("Lab update / note", value=order["lab_notes"] or "", placeholder="Record progress, QC result, dispatch reference, or reason for hold…")
            confirm = st.form_submit_button("Save update", type="primary", use_container_width=True)
            if confirm:
                update_order(chosen, next_status, notes)
                st.success(f"{chosen} updated.")
                st.rerun()
        st.markdown("**Status history**")
        hist = load_history(chosen)
        for _, event in hist.iterrows():
            st.markdown(f'**{event["status"]}** · {event["changed_at"]}  \n{event["note"] or ""}  \n<span class="muted">By {event["changed_by"]}</span>', unsafe_allow_html=True)
            st.divider()

    with tab_all:
        q = st.text_input("Search all orders", placeholder="Order ID, clinic, dentist, patient reference…", key="lab_all_search")
        all_filtered = df.copy()
        if q:
            mask = all_filtered.astype(str).apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
            all_filtered = all_filtered[mask]
        render_order_table(all_filtered)
        csv = all_filtered.to_csv(index=False).encode("utf-8")
        st.download_button("Download filtered orders as CSV", data=csv, file_name="dentalflow_orders.csv", mime="text/csv")


def main():
    init_db()
    inject_css()
    df = load_orders()

    with st.sidebar:
        st.markdown('<div class="brand">🦷 Dental<span>Flow</span></div>', unsafe_allow_html=True)
        st.caption("Dental lab work, in sync.")
        st.divider()
        role = st.radio("WORKSPACE", ["Dentist portal", "Lab dashboard"], label_visibility="visible")
        st.divider()
        st.markdown("**Demo profile**")
        if role == "Dentist portal":
            profile = st.selectbox(
                "View as dentist",
                ["Dr. Maya Rao", "Dr. Arjun Mehta", "Dr. Neha Iyer"],
                label_visibility="collapsed",
            )
            profiles = {
                "Dr. Maya Rao": ("Indiranagar Dental Care", "maya@example.com"),
                "Dr. Arjun Mehta": ("WhiteArc Dental Studio", "arjun@example.com"),
                "Dr. Neha Iyer": ("SmileCraft Clinic", "neha@example.com"),
            }
            clinic, email = profiles[profile]
            st.session_state["dentist_name"] = profile
            st.session_state["clinic_name"] = clinic
            st.session_state["dentist_email"] = email
        else:
            st.markdown("**DentalFlow Lab Team**")
            st.caption("Demo mode · no authentication")
        st.divider()
        st.caption("Prototype v0.1")
        st.caption("Use synthetic patient references only.")

    df = load_orders()
    if role == "Dentist portal":
        dentist_portal(df)
    else:
        lab_dashboard(df)

    st.markdown('<div class="footer-note">DentalFlow · Lab collaboration made clearer · Prototype only</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
