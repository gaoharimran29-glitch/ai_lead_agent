import streamlit as st
import pandas as pd
import smtplib
import time
import os
import io
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from main import graph

# ---------------------------
# Page Config
# ---------------------------

st.set_page_config(
    page_title="PropTech Lead Intelligence",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------------------
# Custom CSS
# ---------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

h1, h2, h3 {
    font-family: 'Syne', sans-serif !important;
}

.stApp {
    background: #0a0a0f;
    color: #e8e8f0;
}

/* Metric cards */
.metric-row {
    display: flex;
    gap: 16px;
    margin-bottom: 32px;
}

.metric-card {
    flex: 1;
    background: #13131a;
    border: 1px solid #1e1e2e;
    border-radius: 12px;
    padding: 20px 24px;
}

.metric-label {
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #5a5a7a;
    margin-bottom: 8px;
}

.metric-value {
    font-family: 'Syne', sans-serif;
    font-size: 32px;
    font-weight: 800;
    color: #e8e8f0;
}

.metric-value.green { color: #4ade80; }
.metric-value.amber { color: #fbbf24; }
.metric-value.blue  { color: #60a5fa; }

/* Lead card */
.lead-card {
    background: #13131a;
    border: 1px solid #1e1e2e;
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 20px;
    transition: border-color 0.2s;
}

.lead-card:hover {
    border-color: #2e2e4e;
}

.lead-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
}

.company-name {
    font-family: 'Syne', sans-serif;
    font-size: 20px;
    font-weight: 700;
    color: #e8e8f0;
}

.score-badge {
    background: #1a1a2e;
    border: 1px solid #2e2e4e;
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 13px;
    font-weight: 600;
    color: #fbbf24;
}

.score-badge.hot {
    background: #1a0f0f;
    border-color: #7f1d1d;
    color: #f87171;
}

.info-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 16px;
}

.info-chip {
    background: #0f0f1a;
    border: 1px solid #1e1e2e;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    color: #8888aa;
    display: flex;
    align-items: center;
    gap: 6px;
}

.info-chip a {
    color: #60a5fa;
    text-decoration: none;
}

.signal-box {
    background: #0f0f1a;
    border-left: 3px solid #3b3b5e;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    margin-bottom: 20px;
    font-size: 13px;
    color: #8888aa;
    line-height: 1.6;
}

.email-preview {
    background: #0d0d18;
    border: 1px solid #1e1e2e;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 16px;
}

.email-header {
    padding: 12px 16px;
    background: #13131a;
    border-bottom: 1px solid #1e1e2e;
    font-size: 12px;
    color: #5a5a7a;
}

.email-subject {
    font-size: 13px;
    color: #c8c8e0;
    font-weight: 500;
}

.email-to {
    margin-top: 4px;
    font-size: 12px;
    color: #5a5a7a;
}

.email-body-preview {
    padding: 16px;
    font-size: 13px;
    color: #8888aa;
    line-height: 1.7;
    white-space: pre-wrap;
}

.divider {
    border: none;
    border-top: 1px solid #1e1e2e;
    margin: 8px 0 24px 0;
}

.confidence-bar-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;
}

.confidence-label {
    font-size: 11px;
    color: #5a5a7a;
    width: 100px;
    flex-shrink: 0;
}

.confidence-track {
    flex: 1;
    height: 4px;
    background: #1e1e2e;
    border-radius: 2px;
    overflow: hidden;
}

.confidence-fill {
    height: 100%;
    border-radius: 2px;
    background: linear-gradient(90deg, #3b82f6, #10b981);
}

.confidence-pct {
    font-size: 11px;
    color: #5a5a7a;
    width: 36px;
    text-align: right;
    flex-shrink: 0;
}

/* Status tags */
.tag-sent {
    display: inline-block;
    background: #052e16;
    border: 1px solid #166534;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 11px;
    color: #4ade80;
    letter-spacing: 1px;
    text-transform: uppercase;
}

.tag-no-email {
    display: inline-block;
    background: #1c1917;
    border: 1px solid #44403c;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 11px;
    color: #78716c;
    letter-spacing: 1px;
    text-transform: uppercase;
}

/* Button overrides */
.stButton > button {
    background: #1e1e2e !important;
    color: #c8c8e0 !important;
    border: 1px solid #2e2e4e !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 13px !important;
    padding: 8px 20px !important;
    transition: all 0.2s !important;
}

.stButton > button:hover {
    background: #2e2e4e !important;
    border-color: #4e4e7e !important;
    color: #e8e8f0 !important;
}

/* Primary button */
div[data-testid="stButton"]:first-of-type > button {
    background: #1a1a3e !important;
    border-color: #3b3b7e !important;
    color: #a0a0ff !important;
}

/* Hide default streamlit elements */
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

/* Section header */
.section-title {
    font-family: 'Syne', sans-serif;
    font-size: 13px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #3b3b5e;
    margin-bottom: 20px;
    padding-bottom: 10px;
    border-bottom: 1px solid #1a1a2a;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------
# Email Sender
# ---------------------------

def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Send email via Gmail SMTP.
    Returns (success: bool, message: str)
    """
    sender_email = os.getenv("EMAIL")
    sender_password = os.getenv("PASSWORD")

    if not sender_email or not sender_password:
        return False, "EMAIL or PASSWORD env variables not set"

    if not to_email:
        return False, "No recipient email address"

    try:
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        return True, "Sent"

    except smtplib.SMTPAuthenticationError:
        return False, "Gmail authentication failed — check EMAIL/PASSWORD in .env"
    except smtplib.SMTPRecipientsRefused:
        return False, f"Recipient refused: {to_email}"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# ---------------------------
# Session State
# ---------------------------

if "leads" not in st.session_state:
    st.session_state.leads = []

if "sent" not in st.session_state:
    st.session_state.sent = {}       # {index: True/False}

if "running" not in st.session_state:
    st.session_state.running = False


# ---------------------------
# Header
# ---------------------------

st.markdown("""
<div style="padding: 40px 0 32px 0;">
    <div style="font-family: Syne, sans-serif; font-size: 11px; letter-spacing: 4px; 
                text-transform: uppercase; color: #3b3b5e; margin-bottom: 10px;">
        AI INTELLIGENCE SYSTEM
    </div>
    <h1 style="font-family: Syne, sans-serif; font-size: 36px; font-weight: 800; 
               color: #e8e8f0; margin: 0 0 8px 0; line-height: 1.1;">
        PropTech Lead Engine
    </h1>
    <p style="color: #5a5a7a; font-size: 14px; margin: 0;">
        Monitors signals → identifies intent → finds contacts → drafts outreach
    </p>
</div>
""", unsafe_allow_html=True)


# ---------------------------
# Pipeline Trigger — runs FIRST so session state is updated before metrics render
# ---------------------------

col_btn, col_status = st.columns([1, 4])

with col_btn:
    run_clicked = st.button("⚡ Find New Leads", use_container_width=True)

if run_clicked:
    with st.spinner("Running AI pipeline — this may take a few minutes..."):
        try:
            result = graph.invoke({})
            new_leads = result.get("leads", [])
            st.session_state.leads = new_leads
            st.session_state.sent = {}
        except Exception as e:
            st.error(f"❌ Pipeline failed: {str(e)}")

    # Rerun forces a full re-render so metrics below read the updated session state
    st.rerun()


# ---------------------------
# Metrics — placed AFTER pipeline trigger so they always read fresh session state
# ---------------------------

leads = st.session_state.leads
total = len(leads)
hot = len([l for l in leads if l.get("Intent Score", 0) >= 8])
with_email = len([l for l in leads if l.get("Email")])
sent_count = len([v for v in st.session_state.sent.values() if v])

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Leads", total)
with col2:
    st.metric("Hot Leads (8+)", hot)
with col3:
    st.metric("With Email", with_email)
with col4:
    st.metric("Emails Sent", sent_count)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)


# ---------------------------
# Lead List
# ---------------------------

if st.session_state.leads:

    st.markdown(f"""
    <div class="section-title">
        {len(st.session_state.leads)} LEADS FOUND
    </div>
    """, unsafe_allow_html=True)

    for i, lead in enumerate(st.session_state.leads):

        score = lead.get("Intent Score", 0)
        score_class = "hot" if score >= 8 else ""
        has_email = bool(lead.get("Email"))
        confidence = lead.get("Email Confidence", 0)
        already_sent = st.session_state.sent.get(i, False)

        # ------ Card open ------
        st.markdown(f"""
        <div class="lead-card">
            <div class="lead-header">
                <div class="company-name">{lead.get("Company Name", "Unknown")}</div>
                <div class="score-badge {score_class}">⚡ {score}/10</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Use columns for info layout
        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown(f"**👤 Contact**")
            st.markdown(f"{lead.get('Contact Name', '—')} · *{lead.get('Title', '')}*")

        with c2:
            st.markdown(f"**📧 Email**")
            if has_email:
                st.markdown(f"`{lead.get('Email')}`")
                # Confidence bar
                conf = int(confidence)
                conf_color = "#4ade80" if conf >= 70 else "#fbbf24" if conf >= 40 else "#f87171"
                st.markdown(f"""
                <div style="display:flex; align-items:center; gap:8px; margin-top:4px;">
                    <div style="flex:1; height:3px; background:#1e1e2e; border-radius:2px;">
                        <div style="width:{conf}%; height:100%; background:{conf_color}; border-radius:2px;"></div>
                    </div>
                    <span style="font-size:11px; color:#5a5a7a;">{conf}%</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#5a5a7a; font-size:13px;'>Not found</span>", unsafe_allow_html=True)

        with c3:
            st.markdown(f"**🔗 Links**")
            if lead.get("LinkedIn URL"):
                st.markdown(f"[LinkedIn Profile]({lead['LinkedIn URL']})")
            if lead.get("Company Website"):
                st.markdown(f"[Company Website]({lead['Company Website']})")

        # Signal summary
        summary = lead.get("Signal Summary", "").strip()
        if summary:
            st.markdown(
                f"""<div style="background:#0f0f1a; border-left:3px solid #3b3b5e;
                    border-radius:0 8px 8px 0; padding:12px 16px; margin:16px 0 20px 0;
                    font-size:13px; color:#8888aa; line-height:1.6;">
                    📰 &nbsp;{summary}
                </div>""",
                unsafe_allow_html=True
            )

        # Email preview
        subject = lead.get("Email Subject", "")
        body = lead.get("Email Body", "")

        if subject or body:
            with st.expander("📩 View Email Draft", expanded=False):

                # Editable subject
                new_subject = st.text_input(
                    "Subject",
                    value=subject,
                    key=f"subj_{i}",
                    label_visibility="collapsed",
                    placeholder="Subject line..."
                )

                # Editable body
                new_body = st.text_area(
                    "Email body",
                    value=body,
                    height=200,
                    key=f"body_{i}",
                    label_visibility="collapsed"
                )

                # Update lead with any edits
                st.session_state.leads[i]["Email Subject"] = new_subject
                st.session_state.leads[i]["Email Body"] = new_body

        # Send button / status
        st.markdown("<div style='margin-top: 12px;'>", unsafe_allow_html=True)

        if already_sent:
            st.markdown("<span class='tag-sent'>✓ Sent</span>", unsafe_allow_html=True)

        elif not has_email:
            st.markdown("<span class='tag-no-email'>No email — cannot send</span>", unsafe_allow_html=True)

        else:
            if st.button(f"📨 Send Email", key=f"send_{i}"):
                final_subject = st.session_state.leads[i].get("Email Subject", "Quick chat?")
                final_body = st.session_state.leads[i].get("Email Body", "")

                if not final_body.strip():
                    st.warning("⚠️ Email body is empty. Please write something first.")
                else:
                    with st.spinner("Sending..."):
                        success, msg = send_email(
                            lead["Email"],
                            final_subject or "Quick chat?",
                            final_body
                        )

                    if success:
                        st.session_state.sent[i] = True
                        st.success("✅ Email sent!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"❌ Failed: {msg}")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

    # ---------------------------
    # Bulk Send Section
    # ---------------------------

    st.markdown("<div class='section-title'>BULK ACTIONS</div>", unsafe_allow_html=True)

    sendable = [
        i for i, lead in enumerate(st.session_state.leads)
        if lead.get("Email")
        and lead.get("Email Body")
        and not st.session_state.sent.get(i)
    ]

    if sendable:
        st.markdown(f"<p style='color:#5a5a7a; font-size:13px; margin-bottom:16px;'>"
                    f"{len(sendable)} leads ready to send</p>", unsafe_allow_html=True)

        if st.button(f"📤 Send All {len(sendable)} Emails"):
            success_count = 0
            fail_count = 0

            progress = st.progress(0)
            status_text = st.empty()

            for idx, i in enumerate(sendable):
                lead = st.session_state.leads[i]
                status_text.text(f"Sending to {lead.get('Contact Name', 'Unknown')}...")

                ok, msg = send_email(
                    lead["Email"],
                    lead.get("Email Subject", "Quick chat?"),
                    lead.get("Email Body", "")
                )

                if ok:
                    st.session_state.sent[i] = True
                    success_count += 1
                else:
                    fail_count += 1
                    st.warning(f"⚠️ Failed for {lead.get('Company Name')}: {msg}")

                progress.progress((idx + 1) / len(sendable))
                time.sleep(2)   # avoid spam

            status_text.empty()
            progress.empty()

            st.success(f"✅ Sent {success_count} emails. {fail_count} failed.")
            st.rerun()

    else:
        st.markdown("<p style='color:#5a5a7a; font-size:13px;'>No sendable leads remaining.</p>",
                    unsafe_allow_html=True)

    # ---------------------------
    # Download Excel
    # ---------------------------

    st.markdown("<div class='section-title' style='margin-top:32px;'>EXPORT</div>", unsafe_allow_html=True)

    excel_path = "data/leads.xlsx"

    if os.path.exists(excel_path):
        with open(excel_path, "rb") as f:
            excel_bytes = f.read()

        st.download_button(
            label="⬇️ Download leads.xlsx",
            data=excel_bytes,
            file_name=f"proptech_leads_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    else:
        # Excel not saved yet — build it from current session leads on the fly
        if st.session_state.leads:
            buffer = io.BytesIO()
            pd.DataFrame(st.session_state.leads).to_excel(buffer, index=False, engine="openpyxl")
            buffer.seek(0)

            st.download_button(
                label="⬇️ Download leads.xlsx",
                data=buffer,
                file_name=f"proptech_leads_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.markdown("<p style='color:#2e2e4e; font-size:13px;'>No leads to export yet.</p>",
                        unsafe_allow_html=True)

else:
    # Empty state
    st.markdown("""
    <div style="text-align: center; padding: 80px 40px;">
        <div style="font-size: 48px; margin-bottom: 16px;">🔍</div>
        <div style="font-family: Syne, sans-serif; font-size: 18px; color: #3b3b5e; margin-bottom: 8px;">
            No leads yet
        </div>
        <div style="font-size: 13px; color: #2e2e4e;">
            Click "Find New Leads" to run the pipeline
        </div>
    </div>
    """, unsafe_allow_html=True)