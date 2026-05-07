import streamlit as st
import requests
import copy
import os

LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "logo.png")

# Sidebar persona selector
with st.sidebar:
    st.image(LOGO_PATH, use_container_width=True)
    st.divider()
    st.markdown("## I am a...")
    persona = st.radio(
        "Select your profile",
        options=["general", "graduate", "switcher"],
        format_func=lambda x: {
            "general": "👤 General",
            "graduate": "🎓 Recent Graduate",
            "switcher": "🔄 Career Switcher",
        }[x],
        key="persona",
        label_visibility="collapsed",
    )
    st.caption({
        "general": "Standard gap analysis.",
        "graduate": "Projects & coursework treated as professional experience. Certifications prioritised.",
        "switcher": "Surfaces transferable hard skills from your existing background.",
    }[persona])

st.subheader("Step 1: Upload Your Resume")

st.info("AI will parse your resume into structured data. You can review and edit the results before continuing.", icon="🤖")

uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])

if uploaded_file is not None:
    if "parsed_resume" not in st.session_state or st.session_state.get("last_file") != uploaded_file.name:
        with st.spinner("Parsing resume with AI..."):
            files = {"file": (uploaded_file.name, uploaded_file, "application/pdf")}
            response = requests.post("http://localhost:8000/parse_resume", files=files)
        if response.ok:
            st.session_state["parsed_resume"] = response.json()
            st.session_state["last_file"] = uploaded_file.name
            st.success("Resume parsed successfully!")
        else:
            st.error(f"Error: {response.json().get('detail', 'Failed to parse resume.')}")
            st.stop()

if "parsed_resume" in st.session_state:
    data = st.session_state["parsed_resume"]
    edited = copy.deepcopy(data)

    # --- Skills ---
    st.markdown("### Skills")
    skills_text = st.text_area(
        "Edit skills (one per line)",
        value="\n".join(data.get("skills", [])),
        height=120,
        key="skills_input",
    )
    edited["skills"] = [s.strip() for s in skills_text.splitlines() if s.strip()]

    # --- Work Experience ---
    st.markdown("### Work Experience")
    work_exp = data.get("work_experience", [])
    edited_work = []
    for i, entry in enumerate(work_exp):
        with st.expander(entry.get("title", f"Entry {i+1}"), expanded=True):
            title = st.text_input("Title", value=entry.get("title", ""), key=f"work_title_{i}")
            desc = st.text_area("Description", value=entry.get("description", ""), key=f"work_desc_{i}", height=100)
            edited_work.append({"title": title, "description": desc})
    edited["work_experience"] = edited_work

    # --- Projects ---
    st.markdown("### Projects")
    projects = data.get("projects", [])
    edited_projects = []
    for i, entry in enumerate(projects):
        with st.expander(entry.get("title", f"Project {i+1}"), expanded=True):
            title = st.text_input("Title", value=entry.get("title", ""), key=f"proj_title_{i}")
            desc = st.text_area("Description", value=entry.get("description", ""), key=f"proj_desc_{i}", height=100)
            edited_projects.append({"title": title, "description": desc})
    edited["projects"] = edited_projects

    # Save edits back to session state
    if st.button("Save Edits"):
        st.session_state["parsed_resume"] = edited
        st.success("Changes saved!")

    with st.expander("View raw JSON"):
        st.json(st.session_state["parsed_resume"])

# --- Step 2: Job Search ---
if "parsed_resume" in st.session_state:
    st.divider()
    st.subheader("Step 2: Find Jobs to Compare Against")

    col1, col2 = st.columns([3, 1])
    with col1:
        job_title = st.text_input("Target job title", placeholder="e.g. AI Engineer, Data Scientist")
    with col2:
        n_jobs = st.number_input("# of jobs", min_value=1, max_value=10, value=2)

    if st.button("Search Jobs", disabled=not job_title):
        with st.spinner(f"Fetching {n_jobs} '{job_title}' job listings..."):
            resp = requests.post(
                "http://localhost:8000/fetch_jobs",
                params={"job_title": job_title, "n": n_jobs},
            )
        if resp.ok:
            st.session_state["jobs"] = resp.json()
            st.session_state["job_title"] = job_title
            st.success(f"Found {len(st.session_state['jobs'])} job listings!")
        else:
            try:
                detail = resp.json().get('detail', 'Failed to fetch jobs.')
            except Exception:
                detail = f"Server error (HTTP {resp.status_code}): {resp.text[:300]}"
            st.error(f"Error: {detail}")

    if "jobs" in st.session_state:
        st.markdown(f"### Job Listings for: _{st.session_state.get('job_title', '')}_")
        for i, job in enumerate(st.session_state["jobs"]):
            with st.expander(job.get("title", f"Job {i+1}"), expanded=False):
                company = job.get("company", "")
                apply_link = job.get("apply_link", "")
                if company:
                    st.markdown(f"**{company}**")
                st.write(job.get("description", ""))
                st.markdown("**Qualifications**")
                for q in job.get("qualifications", []):
                    st.markdown(f"- {q}")
                col_link, col_del = st.columns([4, 1])
                with col_link:
                    if apply_link:
                        st.link_button("Apply Now", apply_link)
                with col_del:
                    if st.button("🗑️ Remove", key=f"remove_job_{i}"):
                        st.session_state["jobs"].pop(i)
                        st.rerun()

        with st.expander("View raw jobs JSON"):
            st.json(st.session_state["jobs"])

    # --- Add job manually ---
    with st.expander("➕ Add a job manually", expanded=False):
        with st.form("manual_job_form", clear_on_submit=True):
            m_title = st.text_input("Job Title *")
            m_company = st.text_input("Company")
            m_description = st.text_area("Description (2-3 sentences about the role)")
            m_qualifications = st.text_area(
                "Qualifications (one per line)",
                placeholder="e.g.\n3+ years Python experience\nFamiliarity with AWS",
            )
            m_apply_link = st.text_input("Application Link (URL)")
            submitted = st.form_submit_button("Add Job")
            if submitted:
                if not m_title.strip():
                    st.warning("Job title is required.")
                else:
                    new_job = {
                        "title": m_title.strip(),
                        "company": m_company.strip(),
                        "description": m_description.strip(),
                        "qualifications": [
                            q.strip()
                            for q in m_qualifications.splitlines()
                            if q.strip()
                        ],
                        "apply_link": m_apply_link.strip(),
                    }
                    if "jobs" not in st.session_state:
                        st.session_state["jobs"] = []
                    st.session_state["jobs"].append(new_job)
                    st.success(f"Added '{m_title.strip()}' to the job list.")
                    st.rerun()
if "parsed_resume" in st.session_state and "jobs" in st.session_state:
    st.divider()
    st.subheader("Step 3: Gap Analysis")

    if st.button("Analyse My Profile"):
        with st.spinner("Comparing your profile against job listings..."):
            resp = requests.post(
                "http://localhost:8000/gap_analysis",
                json={
                    "resume": st.session_state["parsed_resume"],
                    "jobs": st.session_state["jobs"],
                    "job_title": st.session_state.get("job_title", ""),
                    "persona": st.session_state.get("persona", "general"),
                },
            )
        if resp.ok:
            st.session_state["analysis"] = resp.json()
        else:
            try:
                detail = resp.json().get("detail", "Failed to run gap analysis.")
            except Exception:
                detail = f"Server error (HTTP {resp.status_code}): {resp.text[:300]}"
            st.error(f"Error: {detail}")

    if "analysis" in st.session_state:
        analysis = st.session_state["analysis"]
        score = analysis.get("score", 0)

        # Score gauge
        st.markdown("### Match Score")
        color = "green" if score >= 70 else "orange" if score >= 40 else "red"
        st.markdown(
            f"<h1 style='color:{color}; font-size:64px'>{score}<span style='font-size:32px'>/100</span></h1>",
            unsafe_allow_html=True,
        )
        st.progress(score)
        st.write(analysis.get("summary", ""))

        # Transferable skills — career switchers only
        if st.session_state.get("persona") == "switcher" and analysis.get("transferable_skills"):
            st.markdown("#### 🔄 Transferable Skills")
            for s in analysis.get("transferable_skills", []):
                st.markdown(f"- {s}")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### ✅ Strengths")
            for s in analysis.get("strengths", []):
                st.markdown(f"- {s}")
        with col2:
            st.markdown("#### ❌ Gaps")
            for g in analysis.get("gaps", []):
                st.markdown(f"- {g}")

        st.markdown("#### 💡 Suggestions to Improve")
        for s in analysis.get("suggestions", []):
            st.markdown(f"- {s}")



# --- Step 4: Learning Roadmap ---
if "analysis" in st.session_state and st.session_state["analysis"].get("gaps"):
    st.divider()
    st.subheader("Step 4: Your Learning Roadmap")

    if st.button("Generate Learning Roadmap"):
        with st.spinner("Building your personalised roadmap..."):
            resp = requests.post(
                "http://localhost:8000/learning_roadmap",
                json={
                    "gaps": st.session_state["analysis"]["gaps"],
                    "job_title": st.session_state.get("job_title", ""),
                    "persona": st.session_state.get("persona", "general"),
                },
            )
        if resp.ok:
            st.session_state["roadmap"] = resp.json()
        else:
            try:
                detail = resp.json().get("detail", "Failed to generate roadmap.")
            except Exception:
                detail = f"Server error (HTTP {resp.status_code}): {resp.text[:300]}"
            st.error(f"Error: {detail}")

    if "roadmap" in st.session_state:
        roadmap = st.session_state["roadmap"]
        timeframes = ["short-term", "medium-term", "long-term"]
        labels = {
            "short-term": "⚡ Short-term (≤ 1 week)",
            "medium-term": "📅 Medium-term (1–4 weeks)",
            "long-term": "🏗️ Long-term (1+ month)",
        }
        type_icons = {"course": "📚", "project": "🔨", "certification": "🏅"}

        for tf in timeframes:
            items = [r for r in roadmap if r.get("timeframe") == tf]
            if not items:
                continue
            st.markdown(f"### {labels[tf]}")
            for item in items:
                cost_badge = "🆓 Free" if item.get("cost") == "free" else "💳 Paid"
                icon = type_icons.get(item.get("type"), "📌")
                grad_badge = " 🎓 Cert Pick" if (st.session_state.get("persona") == "graduate" and item.get("type") == "certification") else ""
                with st.expander(f"{icon} **{item.get('resource', 'Resource')}** — _{item.get('skill', '')}{grad_badge}_"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Provider", item.get("provider", "—"))
                    col2.metric("Time", item.get("time_estimate", "—"))
                    col3.metric("Cost", cost_badge)
                    url = item.get("url", "")
                    if url:
                        st.markdown(f"[🔗 Open Resource]({url})")
