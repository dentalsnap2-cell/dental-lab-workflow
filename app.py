from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd
import streamlit as st

APP_NAME = "DentalFlow"
BUCKET = "dental-files"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {".stl", ".pdf", ".png", ".jpg", ".jpeg", ".dcm", ".zip"}
ALLOWED_MIME_TYPES = {
    ".stl": {"model/stl", "application/sla", "application/octet-stream"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".dcm": {"application/dicom", "application/octet-stream"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}

st.set_page_config(page_title="DentalFlow", page_icon="🦷", layout="wide")

st.markdown("""
<style>
:root { color-scheme: light; }
.block-container {padding-top: 1.5rem; max-width: 1400px;}
.df-brand {font-size: 1.9rem; font-weight: 800; letter-spacing: -.04em;}
.df-muted {color: #64748b;}
div[data-testid="stMetric"] {background: #f8fafc; border: 1px solid #e2e8f0; padding: 1rem; border-radius: 12px;}
</style>
""", unsafe_allow_html=True)


class DentalFlowError(RuntimeError):
    pass


def config_value(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, "")).strip()


def config() -> tuple[str, str]:
    url = config_value("SUPABASE_URL").rstrip("/")
    key = config_value("SUPABASE_ANON_KEY")
    if not url or not key:
        raise DentalFlowError(
            "Supabase is not configured. Add SUPABASE_URL and SUPABASE_ANON_KEY "
            "to .streamlit/secrets.toml locally or to Streamlit Community Cloud app secrets."
        )
    if not url.startswith("https://"):
        raise DentalFlowError("SUPABASE_URL must use HTTPS.")
    return url, key


class SupabaseAPI:
    """Small REST client that always sends the signed-in user's JWT for RLS checks."""

    def __init__(self, url: str, anon_key: str, access_token: str | None = None):
        self.url = url
        self.anon_key = anon_key
        self.access_token = access_token

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"apikey": self.anon_key, "Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            headers["Authorization"] = f"Bearer {self.anon_key}"
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, path: str, *, auth: bool = False,
                 params: dict | None = None, json_body: Any = None,
                 content: bytes | None = None, headers: dict | None = None) -> Any:
        url = f"{self.url}{path}"
        try:
            response = httpx.request(
                method, url, headers=self._headers(headers), params=params,
                json=json_body, content=content, timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise DentalFlowError("Could not connect to Supabase. Check the URL and network.") from exc
        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("msg") or body.get("message") or body.get("error_description") or body.get("error") or "Request failed"
            except Exception:
                message = "Request failed"
            # Avoid echoing tokens or arbitrary server response details.
            raise DentalFlowError(f"Supabase request failed ({response.status_code}): {message}")
        if response.status_code == 204 or not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.content

    def sign_in(self, email: str, password: str) -> dict:
        return self._request("POST", "/auth/v1/token?grant_type=password",
                             json_body={"email": email, "password": password})

    def sign_up(self, email: str, password: str) -> dict:
        return self._request("POST", "/auth/v1/signup",
                             json_body={"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self._request("POST", "/auth/v1/token?grant_type=refresh_token",
                             json_body={"refresh_token": refresh_token})

    def sign_out(self) -> None:
        if self.access_token:
            self._request("POST", "/auth/v1/logout")

    def get(self, table: str, params: dict) -> list[dict]:
        result = self._request("GET", f"/rest/v1/{table}", params=params)
        return result if isinstance(result, list) else []

    def post(self, table: str, payload: dict, *, prefer: str = "return=representation") -> list[dict]:
        result = self._request("POST", f"/rest/v1/{table}", json_body=payload,
                               headers={"Prefer": prefer})
        return result if isinstance(result, list) else ([] if result is None else [result])

    def patch(self, table: str, params: dict, payload: dict) -> list[dict]:
        result = self._request("PATCH", f"/rest/v1/{table}", params=params,
                               json_body=payload, headers={"Prefer": "return=representation"})
        return result if isinstance(result, list) else ([] if result is None else [result])

    def upload(self, path: str, file_bytes: bytes, content_type: str) -> None:
        encoded_path = "/".join(httpx.QueryParams({"p": path})["p"].split("/"))
        # Storage object paths are URL path components; encode each segment safely.
        from urllib.parse import quote
        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        self._request(
            "POST", f"/storage/v1/object/{BUCKET}/{encoded_path}",
            content=file_bytes,
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )

    def download(self, path: str) -> bytes:
        from urllib.parse import quote
        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        return self._request("GET", f"/storage/v1/object/{BUCKET}/{encoded_path}")

    def signed_url(self, path: str, expires_in: int = 60) -> str:
        from urllib.parse import quote
        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        data = self._request("POST", f"/storage/v1/object/sign/{BUCKET}/{encoded_path}",
                             json_body={"expiresIn": expires_in})
        signed = data.get("signedURL") or data.get("signedUrl") or ""
        if signed.startswith("http"):
            return signed
        return f"{self.url}/storage/v1{signed}"


def set_session(tokens: dict) -> None:
    st.session_state["access_token"] = tokens.get("access_token")
    st.session_state["refresh_token"] = tokens.get("refresh_token")
    st.session_state["token_expires_at"] = datetime.now(timezone.utc).timestamp() + int(tokens.get("expires_in", 3600)) - 60
    st.session_state["user"] = tokens.get("user", {})


def get_api() -> SupabaseAPI:
    url, key = config()
    token = st.session_state.get("access_token")
    expires = st.session_state.get("token_expires_at", 0)
    if token and datetime.now(timezone.utc).timestamp() >= expires:
        refresh = st.session_state.get("refresh_token")
        if not refresh:
            clear_session()
            raise DentalFlowError("Your session expired. Please sign in again.")
        tokens = SupabaseAPI(url, key).refresh(refresh)
        set_session(tokens)
        token = tokens.get("access_token")
    return SupabaseAPI(url, key, token)


def clear_session() -> None:
    for key in ("access_token", "refresh_token", "token_expires_at", "user", "membership"):
        st.session_state.pop(key, None)


def render_auth() -> None:
    st.markdown('<div class="df-brand">🦷 DentalFlow</div>', unsafe_allow_html=True)
    st.caption("Secure dental lab work orders")
    st.info("Accounts are provisioned by your lab administrator. Public self-registration is disabled to prevent unauthorized clinic access.")
    tab_login, tab_reset = st.tabs(["Sign in", "Need access?"])
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Work email", autocomplete="email")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            if not email.strip() or not password:
                st.error("Enter your email and password.")
            else:
                try:
                    url, key = config()
                    tokens = SupabaseAPI(url, key).sign_in(email.strip(), password)
                    if not tokens.get("access_token"):
                        st.error("Sign-in did not return a session. Confirm your email if required, then try again.")
                    else:
                        set_session(tokens)
                        st.rerun()
                except DentalFlowError as exc:
                    st.error(str(exc))
    with tab_reset:
        st.write("Contact your lab administrator to have an account created or your password reset.")
        st.caption("Password reset flows can be enabled later with a verified redirect URL and email provider configuration.")


def load_membership(api: SupabaseAPI) -> dict | None:
    user = st.session_state.get("user", {})
    uid = user.get("id")
    if not uid:
        return None
    rows = api.get("memberships", {
        "select": "id,lab_id,clinic_id,role,active,clinics(id,name,code),labs(id,name)",
        "user_id": f"eq.{uid}",
        "active": "eq.true",
        "limit": "2",
    })
    if not rows:
        return None
    # The first release intentionally supports one active membership per login.
    if len(rows) > 1:
        raise DentalFlowError("This account has multiple active memberships. Ask the lab administrator to resolve the ambiguity.")
    membership = rows[0]
    st.session_state["membership"] = membership
    return membership


def require_membership(api: SupabaseAPI) -> dict | None:
    cached = st.session_state.get("membership")
    if cached:
        return cached
    return load_membership(api)


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def app_header(membership: dict) -> None:
    user = st.session_state.get("user", {})
    with st.sidebar:
        st.markdown("## 🦷 DentalFlow")
        st.caption(safe_text(user.get("email")))
        st.markdown(f"**Role:** `{membership.get('role', 'unknown')}`")
        st.caption("Lab: " + safe_text((membership.get("labs") or {}).get("name", "Dental lab")))
        st.divider()
        if st.button("Sign out", use_container_width=True):
            try:
                get_api().sign_out()
            except Exception:
                pass
            clear_session()
            st.rerun()


def fetch_orders(api: SupabaseAPI, membership: dict) -> list[dict]:
    return api.get("orders", {
        "select": "id,order_number,patient_reference,work_type,shade,due_date,status,priority,notes,created_at,clinic_id,clinics(name,code)",
        "order": "created_at.desc",
        "limit": "500",
    })


def create_order(api: SupabaseAPI, membership: dict, clinic_id: str, patient_reference: str,
                 work_type: str, shade: str, due_date: date, priority: str, notes: str) -> dict:
    payload = {
        "lab_id": membership["lab_id"],
        "clinic_id": clinic_id,
        "patient_reference": patient_reference.strip(),
        "work_type": work_type,
        "shade": shade.strip() or None,
        "due_date": due_date.isoformat(),
        "priority": priority,
        "notes": notes.strip() or None,
        "status": "submitted",
        "created_by": st.session_state["user"]["id"],
    }
    rows = api.post("orders", payload)
    if not rows:
        raise DentalFlowError("Order was not created. Check that your membership has permission.")
    return rows[0]


def main_app() -> None:
    try:
        api = get_api()
        membership = require_membership(api)
        if not membership:
            st.markdown('<div class="df-brand">🦷 DentalFlow</div>', unsafe_allow_html=True)
            st.error("Your account is authenticated but has no active lab membership. Ask the lab administrator to provision your access.")
            st.caption("No work-order data is shown until access is provisioned.")
            if st.button("Sign out"):
                clear_session()
                st.rerun()
            return

        app_header(membership)
        role = membership.get("role")
        clinic = membership.get("clinics") or {}
        lab = membership.get("labs") or {}
        is_lab_staff = role in {"lab_admin", "lab_tech"}
        is_admin = role == "lab_admin"

        st.markdown('<div class="df-brand">DentalFlow</div>', unsafe_allow_html=True)
        st.caption(f"{lab.get('name', 'Dental lab')} · Work orders")
        tabs = st.tabs(["Dashboard", "Orders", "New order", "Clinics" if is_lab_staff else "Account"])
        try:
            orders = fetch_orders(api, membership)
        except DentalFlowError as exc:
            st.error(f"Could not load orders: {exc}")
            orders = []

        with tabs[0]:
            all_count = len(orders)
            in_progress = sum(o.get("status") in {"accepted", "in_production", "quality_check"} for o in orders)
            due_soon = sum(o.get("due_date") == date.today().isoformat() and o.get("status") not in {"ready", "shipped", "delivered", "cancelled"} for o in orders)
            complete = sum(o.get("status") in {"ready", "shipped", "delivered"} for o in orders)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Visible orders", all_count)
            c2.metric("In progress", in_progress)
            c3.metric("Due today", due_soon)
            c4.metric("Ready / shipped", complete)
            st.subheader("Recent work")
            if orders:
                st.dataframe(pd.DataFrame([{
                    "Order": o.get("order_number"),
                    "Clinic": (o.get("clinics") or {}).get("name", "—"),
                    "Patient reference": o.get("patient_reference"),
                    "Work": o.get("work_type"),
                    "Due": o.get("due_date"),
                    "Status": o.get("status"),
                    "Priority": o.get("priority"),
                } for o in orders[:10]]), use_container_width=True, hide_index=True)
            else:
                st.info("No orders yet. Create the first order or ask a clinic to submit one.")

        with tabs[1]:
            st.subheader("Work orders")
            search = st.text_input("Search order number, patient reference, or clinic", key="order_search")
            statuses = ["all", "submitted", "accepted", "in_production", "quality_check", "ready", "shipped", "delivered", "cancelled"]
            chosen_status = st.selectbox("Filter by status", statuses)
            filtered = orders
            if chosen_status != "all":
                filtered = [o for o in filtered if o.get("status") == chosen_status]
            if search.strip():
                term = search.lower().strip()
                filtered = [o for o in filtered if term in " ".join([
                    safe_text(o.get("order_number")), safe_text(o.get("patient_reference")),
                    safe_text((o.get("clinics") or {}).get("name"))
                ]).lower()]
            if filtered:
                st.dataframe(pd.DataFrame([{
                    "Order": o.get("order_number"), "Clinic": (o.get("clinics") or {}).get("name", "—"),
                    "Patient reference": o.get("patient_reference"), "Work": o.get("work_type"),
                    "Shade": o.get("shade") or "—", "Due": o.get("due_date"),
                    "Status": o.get("status"), "Priority": o.get("priority"),
                } for o in filtered]), use_container_width=True, hide_index=True)
                st.download_button("Export visible orders (CSV)", pd.DataFrame(filtered).drop(
                    columns=["clinics"], errors="ignore").to_csv(index=False).encode("utf-8"),
                    file_name="dentalflow-orders.csv", mime="text/csv")
                st.divider()
                st.subheader("Order details and status")
                selected = st.selectbox("Select order", filtered, format_func=lambda o: f"{o.get('order_number')} · {o.get('patient_reference')}")
                st.write(f"**Clinic:** {(selected.get('clinics') or {}).get('name', '—')}")
                st.write(f"**Notes:** {selected.get('notes') or 'No notes'}")
                if is_lab_staff:
                    allowed_statuses = ["submitted", "accepted", "in_production", "quality_check", "ready", "shipped", "delivered", "cancelled"]
                    with st.form("status_update"):
                        new_status = st.selectbox("Update status", allowed_statuses,
                                                  index=allowed_statuses.index(selected.get("status", "submitted")) if selected.get("status") in allowed_statuses else 0)
                        update_note = st.text_input("Status note (optional)")
                        update = st.form_submit_button("Save status", type="primary")
                    if update and new_status != selected.get("status"):
                        try:
                            updated = api.patch("orders", {"id": f"eq.{selected['id']}"}, {
                                "status": new_status,
                                "status_note": update_note.strip() or None,
                                "updated_by": st.session_state["user"]["id"],
                            })
                            if updated:
                                st.success("Status updated.")
                                st.rerun()
                            st.error("No order was updated. Check your role and RLS policies.")
                        except DentalFlowError as exc:
                            st.error(str(exc))
                else:
                    st.caption("Your lab team will update the order status.")
                # File list and upload: clinic members may upload to their own clinic's order;
                # lab staff may upload to any order visible under RLS.
                st.divider()
                st.subheader("Dental files")
                try:
                    file_rows = api.get("order_files", {
                        "select": "id,file_name,object_path,content_type,size_bytes,created_at",
                        "order_id": f"eq.{selected['id']}", "order": "created_at.desc"
                    })
                except DentalFlowError:
                    file_rows = []
                if file_rows:
                    for f in file_rows:
                        left, right = st.columns([4, 1])
                        left.write(f"{f.get('file_name')} · {round((f.get('size_bytes') or 0)/1024/1024, 2)} MB")
                        try:
                            signed = api.signed_url(f["object_path"], 60)
                            right.link_button("Open (60s)", signed)
                        except DentalFlowError:
                            right.caption("No access")
                else:
                    st.caption("No files attached to this order.")
                uploaded = st.file_uploader("Attach STL, PDF, image, DICOM, or ZIP (max 25 MB)",
                                            type=[x.lstrip(".") for x in sorted(ALLOWED_EXTENSIONS)],
                                            key=f"upload-{selected['id']}")
                if uploaded and st.button("Upload file", key=f"upload-button-{selected['id']}"):
                    suffix = "." + uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else ""
                    data = uploaded.getvalue()
                    mime = uploaded.type or "application/octet-stream"
                    if suffix not in ALLOWED_EXTENSIONS:
                        st.error("This file type is not allowed.")
                    elif len(data) > MAX_UPLOAD_BYTES:
                        st.error("File exceeds the 25 MB limit.")
                    elif mime not in ALLOWED_MIME_TYPES.get(suffix, set()):
                        st.error("The file's reported content type does not match the allowed type.")
                    else:
                        path = f"{membership['lab_id']}/{selected['clinic_id']}/{selected['id']}/{uuid.uuid4().hex}{suffix}"
                        try:
                            api.upload(path, data, mime)
                            api.post("order_files", {
                                "lab_id": membership["lab_id"], "clinic_id": selected["clinic_id"],
                                "order_id": selected["id"], "uploaded_by": st.session_state["user"]["id"],
                                "file_name": uploaded.name, "object_path": path,
                                "content_type": mime, "size_bytes": len(data),
                            })
                            st.success("File uploaded.")
                            st.rerun()
                        except DentalFlowError as exc:
                            st.error(f"Upload failed: {exc}")
            else:
                st.info("No orders match these filters.")

        with tabs[2]:
            st.subheader("Create work order")
            if role not in {"lab_admin", "lab_tech", "dentist"}:
                st.warning("Your role cannot create orders.")
            else:
                clinics = api.get("clinics", {"select": "id,name,code", "active": "eq.true", "order": "name.asc"})
                if role == "dentist":
                    clinics = [c for c in clinics if c.get("id") == membership.get("clinic_id")]
                if not clinics:
                    st.info("No active clinics are available to this account.")
                else:
                    with st.form("create_order"):
                        clinic_option = st.selectbox("Clinic", clinics, format_func=lambda c: f"{c['name']} ({c.get('code') or 'no code'})", disabled=(role == "dentist"))
                        patient_ref = st.text_input("Patient reference / case ID", help="Use a clinic's internal case reference; avoid unnecessary patient-identifying information.")
                        work_type = st.selectbox("Work type", ["Crown", "Bridge", "Implant", "Denture", "Veneer", "Aligner / retainer", "Night guard", "Other"])
                        shade = st.text_input("Shade", placeholder="e.g. A2")
                        due = st.date_input("Due date", min_value=date.today())
                        priority = st.selectbox("Priority", ["standard", "rush"])
                        notes = st.text_area("Instructions")
                        create = st.form_submit_button("Create order", type="primary")
                    if create:
                        if not patient_ref.strip():
                            st.error("Enter a patient reference or case ID.")
                        else:
                            try:
                                created = create_order(api, membership, clinic_option["id"], patient_ref, work_type, shade, due, priority, notes)
                                st.success(f"Order {created.get('order_number', created.get('id'))} created.")
                                st.rerun()
                            except DentalFlowError as exc:
                                st.error(str(exc))

        with tabs[3]:
            if is_lab_staff:
                st.subheader("Clinics")
                clinics = api.get("clinics", {"select": "id,name,code,contact_email,phone,active,created_at", "order": "name.asc"})
                if clinics:
                    st.dataframe(pd.DataFrame(clinics), use_container_width=True, hide_index=True)
                else:
                    st.info("No clinics configured yet.")
                if is_admin:
                    st.divider()
                    st.subheader("Add a clinic")
                    with st.form("add_clinic"):
                        name = st.text_input("Clinic name")
                        code = st.text_input("Clinic code (short, unique)")
                        contact = st.text_input("Contact email")
                        phone = st.text_input("Phone")
                        add = st.form_submit_button("Add clinic")
                    if add:
                        if not name.strip() or not code.strip():
                            st.error("Clinic name and code are required.")
                        else:
                            try:
                                api.post("clinics", {
                                    "lab_id": membership["lab_id"], "name": name.strip(),
                                    "code": code.strip().upper(), "contact_email": contact.strip() or None,
                                    "phone": phone.strip() or None,
                                })
                                st.success("Clinic created. Add user memberships through the provisioning instructions in README.")
                                st.rerun()
                            except DentalFlowError as exc:
                                st.error(str(exc))
            else:
                st.subheader("Account")
                st.write("**Email:**", st.session_state.get("user", {}).get("email", "—"))
                st.write("**Clinic:**", clinic.get("name", "—"))
                st.write("**Role:**", role)

    except DentalFlowError as exc:
        st.error(str(exc))
        st.caption("If the problem persists, check the Supabase project URL, anon key, migration status, and RLS policies.")


def main() -> None:
    try:
        config()
    except DentalFlowError as exc:
        st.markdown('<div class="df-brand">🦷 DentalFlow</div>', unsafe_allow_html=True)
        st.error(str(exc))
        st.code('SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"\nSUPABASE_ANON_KEY = "YOUR_SUPABASE_PUBLISHABLE_OR_ANON_KEY"')
        st.stop()
    if not st.session_state.get("access_token"):
        render_auth()
    else:
        main_app()


if __name__ == "__main__":
    main()

