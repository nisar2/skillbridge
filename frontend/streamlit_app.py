import streamlit as st
import requests
import copy
import os

BACKEND_URL = "http://localhost:8000"
LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "logo.png")


# ---------------------------------------------------------------------------
# Authenticated API helper
# ---------------------------------------------------------------------------

def api_call(method: str, path: str, **kwargs) -> requests.Response:
    """Make an API call, injecting the Bearer token when the user is logged in."""
    token = st.session_state.get("token", "")
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return getattr(requests, method)(
        f"{BACKEND_URL}{path}", headers=headers, timeout=30, **kwargs
    )


# ---------------------------------------------------------------------------
# Session restore from ?token=<jwt> URL param
# ---------------------------------------------------------------------------

def _try_restore_session() -> None:
    token = st.query_params.get("token")
    if token and "user" not in st.session_state:
        try:
            resp = requests.get(
                f"{BACKEND_URL}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if resp.ok:
                st.session_state["token"] = token
                st.session_state["user"] = resp.json()
                st.query_params.clear()
        except Exception:
            pass


_try_restore_session()


# ---------------------------------------------------------------------------
# Login screen
# ---------------------------------------------------------------------------

if "user" not in st.session_state:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, use_container_width=True)
        st.markdown("## Welcome to Skill-Bridge")
        st.markdown(
            "Track your career progress, analyse skill gaps, and build a "
            "personalised learning roadmap — all saved to your account."
        )
        st.divider()
        st.link_button(
            "Sign in with Google",
            f"{BACKEND_URL}/auth/google",
            use_container_width=True,
        )
    st.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_search(search_id: str, job_title: str) -> None:
    """Populate session state from a saved Firestore search."""
    st.session_state["current_search_id"] = search_id
    st.session_state["job_title"] = job_title
    st.session_state.pop("last_file", None)

    r = api_call("get", f"/searches/{search_id}/jobs")
    st.session_state["jobs"] = r.json() if r.ok else []

    r = api_call("get", f"/searches/{search_id}/resume")
    if r.ok:
        st.session_state["parsed_resume"] = r.json()
    else:
        st.session_state.pop("parsed_resume", None)

    r = api_call("get", f"/searches/{search_id}/analysis")
    if r.ok:
        st.session_state["analysis"] = r.json()
    else:
        st.session_state.pop("analysis", None)

    r = api_call("get", f"/searches/{search_id}/roadmap")
    roadmap = r.json() if r.ok else []
    st.session_state["roadmap"] = roadmap

    # Initialise checkbox state from saved completion flags
    for item in roadmap:
        ck = f"roadmap_check_{item.get('id', '')}"
        if ck not in st.session_state:
            st.session_state[ck] = item.get("completed", False)


def _persist_jobs() -> None:
    """Save the current session_state["jobs"] list to Firestore."""
    search_id = st.session_state.get("current_search_id")
    if not search_id:
        return
    api_call(
        "put",
        f"/searches/{search_id}/jobs",
        json={"jobs": st.session_state.get("jobs", [])},
    )


# ---------------------------------------------------------------------------
# Sidebar (visible once logged in)
# ---------------------------------------------------------------------------

user = st.session_state["user"]

with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
    st.divider()
    photo = user.get("photo_url", "")
    if photo:
        st.image(photo, width=48)
    st.markdown(f"**{user.get('name', 'User')}**")
    st.caption(user.get("email", ""))
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
    st.caption(
        {
            "general": "Standard gap analysis.",
            "graduate": "Projects & coursework treated as professional experience. Certifications prioritised.",
            "switcher": "Surfaces transferable hard skills from your existing background.",
        }[persona]
    )
    st.divider()

    if "current_search_id" in st.session_state:
        if st.button("← Dashboard", use_container_width=True):
            for k in [
                "current_search_id", "job_title", "jobs",
                "parsed_resume", "last_file", "analysis", "roadmap",
            ]:
                st.session_state.pop(k, None)
            st.rerun()

    if st.button("Sign out", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# ===========================================================================
# Dashboard  (shown when no search is active)
# ===========================================================================

if "current_search_id" not in st.session_state:
    st.subheader("Your Job Searches")

    resp = api_call("get", "/searches")
    searches = resp.json() if resp.ok else []

    if searches:
        for search in searches:
            score = search.get("score")
            if score is None:
                score_md = ":grey[No analysis yet]"
            elif score >= 90:
                score_md = f":green[**{score}/100**]"
            elif score >= 60:
                score_md = f":orange[**{score}/100**]"
            else:
                score_md = f":red[**{score}/100**]"

            c1, c2, c3 = st.columns([3, 1, 1])
            with c1:
                st.markdown(f"**{search['job_title']}**")
                st.caption(f"Updated {search.get('updated_at', '')[:10]}")
            with c2:
                st.markdown(score_md)
            with c3:
                if st.button("Open", key=f"open_{search['id']}"):
                    _load_search(search["id"], search["job_title"])
                    st.rerun()
            st.divider()
    else:
        st.info("No saved searches yet. Start one below.")

    st.subheader("➕ Start New Search")
    with st.form("new_search_form"):
        new_title = st.text_input(
            "Target job title", placeholder="e.g. Data Scientist, ML Engineer"
        )
        if st.form_submit_button("Create Search") and new_title.strip():
            r = api_call("post", "/searches", json={"job_title": new_title.strip()})
            if r.ok:
                d = r.json()
                st.session_state["current_search_id"] = d["search_id"]
                st.session_state["job_title"] = d["job_title"]
                st.session_state["jobs"] = []
                st.session_state.pop("parsed_resume", None)
                st.session_state.pop("analysis", None)
                st.session_state["roadmap"] = []
                st.rerun()
            else:
                st.error("Failed to create search.")
    st.stop()


# ===========================================================================
# Wizard  (current_search_id is set)
# ===========================================================================

search_id = st.session_state["current_search_id"]

st.markdown(f"### 🔍 {st.session_state.get('job_title', '')}")
st.divider()


# ---------------------------------------------------------------------------
# Step 1: Job Search
# ---------------------------------------------------------------------------

st.subheader("Step 1: Find Jobs to Compare Against")

col1, col2 = st.columns([3, 1])
with col1:
    job_title_input = st.text_input(
        "Search for jobs",
        placeholder="e.g. AI Engineer, Data Scientist",
        value=st.session_state.get("job_title", ""),
    )
with col2:
    n_jobs = st.number_input("# of jobs", min_value=1, max_value=10, value=3)

if st.session_state.get("jobs"):
    st.caption(
        f"{len(st.session_state['jobs'])} jobs saved. "
        "Searching again will replace them."
    )

if st.button("Search Jobs", disabled=not job_title_input):
    with st.spinner(f"Fetching {n_jobs} '{job_title_input}' listings..."):
        resp = api_call(
            "post",
            "/fetch_jobs",
            params={"job_title": job_title_input, "n": n_jobs, "search_id": search_id},
        )
    if resp.ok:
        st.session_state["jobs"] = resp.json()
        st.session_state["job_title"] = job_title_input
        # Invalidate downstream results since jobs changed
        st.session_state.pop("analysis", None)
        st.session_state.pop("roadmap", None)
        st.success(f"Found {len(st.session_state['jobs'])} listings — saved.")
    else:
        try:
            detail = resp.json().get("detail", "Failed to fetch jobs.")
        except Exception:
            detail = f"Server error ({resp.status_code}): {resp.text[:200]}"
        st.error(f"Error: {detail}")

if st.session_state.get("jobs"):
    st.markdown(f"### Listings for: _{st.session_state.get('job_title', '')}_")
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
            c_link, c_del = st.columns([4, 1])
            with c_link:
                if apply_link:
                    st.link_button("Apply Now", apply_link)
            with c_del:
                if st.button("🗑️ Remove", key=f"remove_job_{i}"):
                    st.session_state["jobs"].pop(i)
                    _persist_jobs()
                    st.rerun()

    with st.expander("View raw jobs JSON"):
        st.json(st.session_state["jobs"])

with st.expander("➕ Add a job manually", expanded=False):
    with st.form("manual_job_form", clear_on_submit=True):
        m_title = st.text_input("Job Title *")
        m_company = st.text_input("Company")
        m_description = st.text_area("Description (2-3 sentences)")
        m_qualifications = st.text_area(
            "Qualifications (one per line)",
            placeholder="e.g.\n3+ years Python\nFamiliarity with AWS",
        )
        m_apply_link = st.text_input("Application Link (URL)")
        if st.form_submit_button("Add Job"):
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
                _persist_jobs()
                st.success(f"Added '{m_title.strip()}'.")
                st.rerun()


# ---------------------------------------------------------------------------
# Step 2: Upload Resume
# ---------------------------------------------------------------------------

if st.session_state.get("jobs"):
    st.divider()
    st.subheader("Step 2: Upload Your Resume")

    if "parsed_resume" in st.session_state:
        st.info("Resume loaded from saved data. Re-upload a PDF to replace it.", icon="✅")
    else:
        st.info("AI will parse your resume into structured data.", icon="🤖")

    uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])

    if uploaded_file is not None:
        if st.session_state.get("last_file") != uploaded_file.name:
            with st.spinner("Parsing resume with AI..."):
                response = api_call(
                    "post",
                    "/parse_resume",
                    files={"file": (uploaded_file.name, uploaded_file, "application/pdf")},
                    params={"search_id": search_id},
                )
            if response.ok:
                st.session_state["parsed_resume"] = response.json()
                st.session_state["last_file"] = uploaded_file.name
                # Invalidate downstream results since resume changed
                st.session_state.pop("analysis", None)
                st.session_state.pop("roadmap", None)
                st.success("Resume parsed and saved.")
            else:
                try:
                    detail = response.json().get("detail", "Failed to parse resume.")
                except Exception:
                    detail = f"Server error ({response.status_code}): {response.text[:200]}"
                st.error(f"Error: {detail}")
                st.stop()

    if "parsed_resume" in st.session_state:
        data = st.session_state["parsed_resume"]
        edited = copy.deepcopy(data)

        st.markdown("### Skills")
        skills_text = st.text_area(
            "Edit skills (one per line)",
            value="\n".join(data.get("skills", [])),
            height=120,
            key="skills_input",
        )
        edited["skills"] = [s.strip() for s in skills_text.splitlines() if s.strip()]

        st.markdown("### Work Experience")
        edited_work = []
        for i, entry in enumerate(data.get("work_experience", [])):
            with st.expander(entry.get("title", f"Entry {i+1}"), expanded=True):
                title = st.text_input(
                    "Title", value=entry.get("title", ""), key=f"work_title_{i}"
                )
                desc = st.text_area(
                    "Description",
                    value=entry.get("description", ""),
                    key=f"work_desc_{i}",
                    height=100,
                )
                edited_work.append({"title": title, "description": desc})
        edited["work_experience"] = edited_work

        st.markdown("### Projects")
        edited_projects = []
        for i, entry in enumerate(data.get("projects", [])):
            with st.expander(entry.get("title", f"Project {i+1}"), expanded=True):
                title = st.text_input(
                    "Title", value=entry.get("title", ""), key=f"proj_title_{i}"
                )
                desc = st.text_area(
                    "Description",
                    value=entry.get("description", ""),
                    key=f"proj_desc_{i}",
                    height=100,
                )
                edited_projects.append({"title": title, "description": desc})
        edited["projects"] = edited_projects

        if st.button("Save Edits"):
            st.session_state["parsed_resume"] = edited
            r = api_call(
                "put",
                f"/searches/{search_id}/resume",
                json={"resume": edited},
            )
            if r.ok:
                st.success("Changes saved.")
            else:
                st.warning("Saved locally but failed to sync to database.")

        with st.expander("View raw JSON"):
            st.json(st.session_state["parsed_resume"])


# ---------------------------------------------------------------------------
# Step 3: Gap Analysis
# ---------------------------------------------------------------------------

if st.session_state.get("parsed_resume") and st.session_state.get("jobs"):
    st.divider()
    st.subheader("Step 3: Gap Analysis")

    has_analysis = "analysis" in st.session_state
    c_run, c_refresh = st.columns([2, 1])
    with c_run:
        run_analysis = st.button("Analyse My Profile", disabled=has_analysis)
    with c_refresh:
        refresh_analysis = st.button("🔄 Refresh Analysis", disabled=not has_analysis)

    if run_analysis or refresh_analysis:
        with st.spinner("Comparing your profile against job listings..."):
            resp = api_call(
                "post",
                "/gap_analysis",
                json={
                    "resume": st.session_state["parsed_resume"],
                    "jobs": st.session_state["jobs"],
                    "job_title": st.session_state.get("job_title", ""),
                    "persona": st.session_state.get("persona", "general"),
                    "search_id": search_id,
                },
            )
        if resp.ok:
            st.session_state["analysis"] = resp.json()
            # Invalidate roadmap since analysis changed
            st.session_state.pop("roadmap", None)
        else:
            try:
                detail = resp.json().get("detail", "Failed to run gap analysis.")
            except Exception:
                detail = f"Server error ({resp.status_code}): {resp.text[:200]}"
            st.error(f"Error: {detail}")

    if "analysis" in st.session_state:
        analysis = st.session_state["analysis"]
        score = analysis.get("score", 0)

        st.markdown("### Match Score")
        color = "green" if score >= 90 else "orange" if score >= 60 else "red"
        st.markdown(
            f"<h1 style='color:{color}; font-size:64px'>{score}"
            f"<span style='font-size:32px'>/100</span></h1>",
            unsafe_allow_html=True,
        )
        st.progress(score)
        st.write(analysis.get("summary", ""))

        if st.session_state.get("persona") == "switcher" and analysis.get(
            "transferable_skills"
        ):
            st.markdown("#### 🔄 Transferable Skills")
            for s in analysis["transferable_skills"]:
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


# ---------------------------------------------------------------------------
# Step 4: Learning Roadmap
# ---------------------------------------------------------------------------

if st.session_state.get("analysis") and st.session_state["analysis"].get("gaps"):
    st.divider()
    st.subheader("Step 4: Your Learning Roadmap")

    has_roadmap = bool(st.session_state.get("roadmap"))
    c_gen, c_ref = st.columns([2, 1])
    with c_gen:
        gen_roadmap = st.button("Generate Learning Roadmap", disabled=has_roadmap)
    with c_ref:
        refresh_roadmap = st.button("🔄 Refresh Roadmap", disabled=not has_roadmap)

    if gen_roadmap or refresh_roadmap:
        with st.spinner("Building your personalised roadmap..."):
            resp = api_call(
                "post",
                "/learning_roadmap",
                json={
                    "gaps": st.session_state["analysis"]["gaps"],
                    "job_title": st.session_state.get("job_title", ""),
                    "persona": st.session_state.get("persona", "general"),
                    "search_id": search_id,
                },
            )
        if resp.ok:
            st.session_state["roadmap"] = resp.json()
            # Initialise checkbox state from DB-persisted completion flags
            for item in st.session_state["roadmap"]:
                ck = f"roadmap_check_{item.get('id', '')}"
                st.session_state[ck] = item.get("completed", False)
        else:
            try:
                detail = resp.json().get("detail", "Failed to generate roadmap.")
            except Exception:
                detail = f"Server error ({resp.status_code}): {resp.text[:200]}"
            st.error(f"Error: {detail}")

    if st.session_state.get("roadmap"):
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
                item_id = item.get("id", "")
                ck = f"roadmap_check_{item_id}"

                # Detect checkbox toggle from the previous render and sync to DB
                if item_id and ck in st.session_state:
                    new_val = st.session_state[ck]
                    if new_val != item.get("completed", False):
                        api_call(
                            "patch",
                            f"/searches/{search_id}/roadmap/{item_id}",
                            json={"completed": new_val},
                        )
                        item["completed"] = new_val

                completed = item.get("completed", False)
                cost_badge = "🆓 Free" if item.get("cost") == "free" else "💳 Paid"
                icon = type_icons.get(item.get("type"), "📌")
                grad_badge = (
                    " 🎓 Cert Pick"
                    if (
                        st.session_state.get("persona") == "graduate"
                        and item.get("type") == "certification"
                    )
                    else ""
                )
                done_mark = " ✓" if completed else ""
                label = (
                    f"{icon} **{item.get('resource', 'Resource')}**{done_mark}"
                    f" — _{item.get('skill', '')}{grad_badge}_"
                )

                with st.expander(label, expanded=not completed):
                    st.checkbox("Mark complete", key=ck)
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Provider", item.get("provider", "—"))
                    col2.metric("Time", item.get("time_estimate", "—"))
                    col3.metric("Cost", cost_badge)
                    url = item.get("url", "")
                    if url:
                        st.markdown(f"[🔗 Open Resource]({url})")
