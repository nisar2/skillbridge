# Skill-Bridge Career Navigator

An AI-powered career tool that finds real job listings, parses a PDF resume, analyses skill gaps against those listings, and generates a personalised learning roadmap with verified resource URLs — all persisted per-user via Firebase Firestore and secured with Google OAuth 2.0.

🎥 Video Presentation *(link coming soon)*

📊 [Slide Deck](https://docs.google.com/presentation/d/16oonIEplB5HSoW5fj9-vSnraVWM9CUUfhHlZ4dj3D74/edit?usp=sharing)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Authentication & Persistence Layer](#authentication--persistence-layer)
3. [How the Application Works](#how-the-application-works)
   - [Step 1 – Job Search](#step-1--job-search)
   - [Step 2 – Resume Upload & Parsing](#step-2--resume-upload--parsing)
   - [Step 3 – Gap Analysis](#step-3--gap-analysis)
   - [Step 4 – Learning Roadmap](#step-4--learning-roadmap)
4. [Persona System](#persona-system)
5. [Exact Prompts](#exact-prompts)
6. [Design Decisions & Tradeoffs](#design-decisions--tradeoffs)
7. [Getting Started on a New Machine](#getting-started-on-a-new-machine)

---

## Architecture Overview

The pipeline has three parallel inputs that converge into a two-stage AI processing pipeline:

**Persona Selection** — The user picks a persona (Recent Grad or Career Switcher) before running any analysis. The selected persona flows as a context modifier into both the Skill Gap Analysis and the Upskill Roadmap Generator, shaping how results are weighted and presented. A General option is also available which skips the persona context modification.

**Job Search** — A job title string is used to query the [`JSearch API`](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) (via RapidAPI) for real, recently-posted listings. OpenAI then cleans and normalises the raw results into a structured **Relevant Jobs JSON** array using `gpt-4o-mini`.

**Resume Parsing** — A PDF resume is fed through [`pdfplumber`](https://github.com/jsvine/pdfplumber) to extract raw text, which is then sent to OpenAI ([`gpt-4o-mini`](https://developers.openai.com/api/docs/models/gpt-4o-mini)) to produce a structured **Current Experience JSON** containing skills, work experience, and projects.

---

The three outputs feed into the two-stage AI pipeline:

**Skill Gap Analysis** — `gpt-4o-mini` receives the Selected Persona, Current Experience JSON, and Relevant Jobs JSON simultaneously. It returns a **Score** (0–100) and a **gap JSON** listing strengths, gaps, and suggestions — all scoped to hard skills only.

**Upskill Roadmap Generator** — `gpt-4o-mini` uses the Score and gap JSON to generate a personalised learning plan. [`Brave Search`](https://brave.com/search/api/) then enriches each roadmap item with a real resource URL. The final output is a **list of resources to fill the identified gaps, organised by time required** (short-term, medium-term, long-term).

---

**Implementation notes**

- The frontend ([`Streamlit`](https://streamlit.io/)) and backend ([`FastAPI`](https://fastapi.tiangolo.com/)) communicate over HTTP.
- `FastAPI` was chosen over `Flask` for its native async support, which is leveraged during the `Brave Search` URL lookups running concurrently inside the **Upskill Roadmap Generator**.
- `Streamlit` was chosen so the entire UI could be written in Python without HTML/CSS/JS.
- In-flight wizard state is maintained in `st.session_state`. All completed steps are persisted to Firebase Firestore (when authenticated) so users can return to past searches without re-running the pipeline.

---

## Authentication & Persistence Layer

### Google OAuth 2.0 (`backend/auth.py`)

Authentication uses a standard server-side OAuth 2.0 authorization code flow — no client-side JS libraries involved.

**Flow:**

1. Browser navigates to `GET /auth/google`.
2. Backend generates a cryptographically random `state` token (stored in an in-memory dict for CSRF validation), builds the Google consent URL, and issues a `302` redirect to Google.
3. After the user authenticates, Google redirects to `GET /auth/callback?code=…&state=…`.
4. Backend validates the `state` token (one-time use, deleted after check), exchanges the `code` for a Google access token, fetches user info from Google's `/oauth2/v3/userinfo` endpoint, and upserts a `users/{uid}` document in Firestore.
5. Backend signs an **HS256 JWT** (7-day expiry, `python-jose`) containing `{uid, email, name, photo_url}` and issues a `302` redirect to the Streamlit URL with `?token=<jwt>` appended.
6. Streamlit reads the `token` query param on load, calls `GET /auth/me` to validate it, and stores the decoded user in `st.session_state`.

Protected routes use a `get_current_user` FastAPI dependency that reads the `Authorization: Bearer <token>` header and raises `HTTP 401` on invalid or expired tokens. An `get_optional_user` variant returns `None` instead of raising, used by AI routes that work both authenticated and unauthenticated.

### Firestore Persistence (`backend/firestore_db.py`)

All Firestore operations are synchronous at the SDK level (firebase-admin uses gRPC). They are wrapped in `asyncio.to_thread` calls to avoid blocking FastAPI's event loop.

**Document schema:**

```
users/{uid}
  ├── searches/{search_id}           # job_title, score, created_at, updated_at
  │     ├── jobs/{job_id}            # cleaned job objects
  │     ├── resume (id="data")       # parsed resume JSON
  │     ├── analysis (id="data")     # gap analysis result + score
  │     └── roadmap/{item_id}        # roadmap items with completed flag
```

**Key design choices:**

- **Upsert on login:** `upsert_user` creates the `users/{uid}` doc on first login and updates only mutable profile fields (name, photo) on subsequent logins, preserving `created_at`.
- **Score denormalisation:** The gap analysis score is written to both `analysis/data` (full result) and the parent `searches/{search_id}` document. This allows the dashboard to display scores across all past searches with a single collection query rather than N subcollection fetches.
- **Roadmap completion state preservation:** `save_roadmap` merges new roadmap items against any existing `completed=True` flags in the database, so re-generating the roadmap doesn't reset progress on items the user has already checked off.
- **Lazy Firebase init:** `_get_db()` initialises the Firebase Admin SDK on first call. It prefers a local `firebase_service_account.json` file and falls back to Application Default Credentials for cloud deployments (e.g. Cloud Run).

### Dashboard

When a user logs in they land on a dashboard listing all their past searches ordered by `updated_at` descending. Each search card shows the job title, timestamp, and a colour-coded score badge (green ≥ 90, orange ≥ 60, red < 60). Clicking a search restores it as the active session — the wizard re-hydrates `st.session_state` from Firestore before rendering.

---

## How the Application Works

### Step 1 – Job Search

The user enters a target job title and selects how many listings to fetch (1–10). The frontend calls `POST /fetch_jobs?job_title=...&n=...`. A `search_id` is created in Firestore at this point if the user is authenticated.

**What the backend does:**

1. Calls the `JSearch API` with `date_posted: "week"` so only recent listings appear.
2. For each raw job, `_build_job_text()` assembles a text block containing title, company, description (capped at 3,000 chars), and qualifications pulled from three JSearch fields: `job_highlights.Qualifications`, `job_required_skills`, and `job_required_experience`.
3. All N job texts are sent to `gpt-4o-mini` in **a single batch call** (the job-extraction prompt), which returns a JSON array of cleaned job objects.
4. After the OpenAI call, `company` and `apply_link` are **overwritten from raw JSearch data** rather than taken from the model output. `JSearch` is the authoritative source for these values; asking the model to copy them introduces unnecessary transcription errors.
5. If OpenAI extraction fails or returns fewer items than expected, `_fallback_job()` fills the gaps directly from the raw JSearch response.
6. If the request includes a valid `Authorization` header and a `search_id`, the cleaned jobs are saved to `users/{uid}/searches/{search_id}/jobs/`.

**What the frontend does:**

- Displays each job in a collapsible expander showing company, description, qualifications list, an **Apply Now** link button, and a **🗑️ Remove** button that calls `st.session_state["jobs"].pop(i)` and reruns the page.
- Always shows an **Add a job manually** form so users can paste in a job ad from any source not covered by JSearch.
- A **View raw jobs JSON** expander lets technical users inspect the full payload.

---

### Step 2 – Resume Upload & Parsing

The user uploads a PDF resume. The frontend sends it as a multipart file to `POST /parse_resume`.

**What the backend does:**

1. Writes the PDF to a temporary file on disk.
2. Uses `pdfplumber` to extract raw text from every page.
3. Sends the extracted text to `gpt-4o-mini` with the resume-parse prompt (see [Exact Prompts](#exact-prompts)).
4. Returns structured JSON: `{ projects, work_experience, skills }`.
5. If authenticated with a `search_id`, saves the result to `users/{uid}/searches/{search_id}/resume`.

**What the frontend does:**

- Caches the result in `st.session_state["parsed_resume"]` keyed by filename so re-uploading the same file is a no-op.
- Renders editable form fields for every section (skills text area, per-entry expanders for work experience and projects) so the user can correct any parsing errors before proceeding.
- A **Save Edits** button writes the corrected data back to session state and pushes the update to Firestore.

---

### Step 3 – Gap Analysis

Once a resume and at least one job are present, the **Analyse My Profile** button becomes active. The frontend calls `POST /gap_analysis` with the full resume JSON, all job objects, the target job title, and the selected persona.

**What the backend does:**

1. Looks up the persona-specific context string from `PERSONA_GAP_CONTEXTS` (empty string for `"general"`).
2. For the `"switcher"` persona, injects an extra JSON field instruction (`"transferable_skills"`) into the prompt so the model returns that section.
3. Sends the assembled prompt to `gpt-4o-mini` at `temperature=0` for deterministic results.
4. Returns: `{ score, summary, strengths, gaps, suggestions }` plus optionally `transferable_skills`.
5. If authenticated, saves the full result to `users/{uid}/searches/{search_id}/analysis` and denormalises the score up to the parent `searches/{search_id}` document.

**What the frontend does:**

- Renders the score as a large colour-coded number (green ≥ 90, orange ≥ 60, red < 60) with a progress bar.
- Displays summary text, then strengths and gaps in two side-by-side columns.
- Shows the **🔄 Transferable Skills** section only when the `"switcher"` persona is active and the model returned that field.
- Suggestions appear below as a bulleted action list.

---

### Step 4 – Learning Roadmap

Available only after gap analysis has run and found at least one gap. The **Generate Learning Roadmap** button calls `POST /learning_roadmap` with the list of gaps, the job title, and the persona.

**What the backend does:**

1. Looks up the persona-specific context string from `PERSONA_ROADMAP_CONTEXTS`.
2. Sends the roadmap prompt to `gpt-4o-mini` at `temperature=0.2` (slight creativity allowed for resource suggestions).
3. For each roadmap item, fires a `Brave Search` query (`"{resource name} {provider}"`) to fetch a real URL. All queries run concurrently via `asyncio.gather` with a `Semaphore(5)` to stay within Brave's rate limits.
4. Returns the enriched array: `[ { skill, resource, provider, type, cost, time_estimate, timeframe, url } ]`.
5. If authenticated, saves the roadmap to `users/{uid}/searches/{search_id}/roadmap/`, merging against any existing completion state.

**What the frontend does:**

- Groups items into three timeframe buckets: ⚡ Short-term (≤ 1 week), 📅 Medium-term (1–4 weeks), 🏗️ Long-term (1+ month).
- Each card shows a type icon (📚 course, 🔨 project, 🏅 certification), provider, time estimate, and cost badge.
- A **🔗 Open Resource** link points to the real URL retrieved by Brave Search.
- Each item has a checkbox; toggling it calls `PATCH /searches/{search_id}/roadmap/{item_id}` which flips the `completed` flag in Firestore. Progress persists across sessions.
- When the `"graduate"` persona is active, certification items get a **🎓 Cert Pick** badge.

---

## Persona System

The persona is selected in the sidebar and is passed to both `/gap_analysis` and `/learning_roadmap` as a string parameter. There are three values:

### `general` (default)

No persona context is injected. The model applies standard gap analysis and roadmap generation without any special weighting or extra fields.

### `graduate` — Recent Graduate

**Gap analysis context injected:**
> "Persona note: This candidate is a recent graduate. Treat academic projects, coursework, and internships as equivalent to professional work experience. Weight the presence of relevant certifications highly in scoring."

**Roadmap context injected:**
> "Persona note: This candidate is a recent graduate. Prioritise certifications in the roadmap — they provide immediate, verifiable credibility for candidates with limited professional experience."

**UI effects:** Certification roadmap items display a **🎓 Cert Pick** badge.

### `switcher` — Career Switcher

**Gap analysis context injected:**
> "Persona note: This candidate is switching careers from a different industry. Add a 'transferable_skills' array to the JSON output listing hard skills from their background that directly apply to this role. Recognise cross-industry technical skills (e.g. data analysis, scripting, cloud tools) as partial matches."

**Roadmap context injected:**
> "Persona note: This candidate is switching careers. Where possible, suggest resources that explicitly bridge their prior domain to the target role and build on their existing background."

**UI effects:** The gap analysis results include a **🔄 Transferable Skills** section that would otherwise be hidden.

## Exact Prompts

### Resume Parse Prompt (`RESUME_PARSE_PROMPT`)

Sent to `gpt-4o-mini` at `temperature=0`.

```
You are a resume parser. Extract the following structured information from the resume text below and return ONLY valid JSON with no markdown or extra text.

Return this exact structure:
{
  "projects": [
    {"title": "...", "description": "..."}
  ],
  "work_experience": [
    {"title": "...", "description": "..."}
  ],
  "skills": ["skill1", "skill2", "..."]
}

Rules:
- "title" for work_experience should be the job title and company (e.g. "Software Engineer at Acme Corp")
- "description" should be a concise summary of responsibilities/achievements
- "skills" should be a flat list of individual skills (technologies, languages, tools, soft skills)
- If a section is missing from the resume, return an empty list for it

Resume text:
{resume_text}
```

---

### Job Extraction Prompt (`JOB_EXTRACT_PROMPT`)

Sent to `gpt-4o-mini` at `temperature=0`. `{n}` is the number of jobs requested; `{jobs_text}` is all N raw job blocks concatenated.

```
You are a job description parser. Given the list of raw job postings below, extract structured data for ALL of them and return ONLY a valid JSON array with no markdown or extra text.

Return this exact structure (an array, one object per job):
[
  {
    "title": "...",
    "description": "...",
    "qualifications": ["...", "..."]
  },
  ...
]

Rules:
- "title" is the job title
- "description" is a 2-3 sentence summary of the role
- "qualifications" is a combined list of all required and preferred skills and experience
- Return exactly {n} objects in the array, one per job posting below

Job postings:
{jobs_text}
```

---

### Gap Analysis Prompt (`GAP_ANALYSIS_PROMPT`)

Sent to `gpt-4o-mini` at `temperature=0`. `{persona_context}` is the persona string or empty. `{transferable_skills_field}` is either a JSON field snippet (switcher) or empty.

```
You are a career coach AI. Compare the candidate's resume profile against a set of job descriptions for the role of "{job_title}" and return ONLY valid JSON with no markdown or extra text.

{persona_context}

Return this exact structure:
{
  "score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "strengths": ["<bullet 1>", "<bullet 2>", ...],
  "gaps": ["<bullet 1>", "<bullet 2>", ...],
  "suggestions": ["<bullet 1>", "<bullet 2>", ...]{transferable_skills_field}
}

Hard skills only:
- Focus EXCLUSIVELY on technical and hard skills: programming languages, frameworks, tools, platforms, methodologies, domain knowledge, and certifications.
- IGNORE all soft skills (e.g. communication, collaboration, teamwork, leadership, problem-solving, time management). Do not include them in strengths, gaps, or suggestions.

Scoring rules:
- Base the score ENTIRELY on hard skills and hands-on technical experience. Ignore education level and degree requirements.
- Extract implicit hard skills from the candidate's project descriptions and work experience descriptions, not just the explicit skills list.
- Compare those skills against the minimum and preferred qualifications AND the job descriptions.
- Weight minimum qualifications more heavily than preferred qualifications.
- 80-100: Candidate demonstrates most or all required hard skills either explicitly or through project/work experience
- 60-79: Candidate has the core hard skills but is missing some meaningful technical qualifications
- 40-59: Candidate has transferable technical skills but notable hard skill gaps exist
- 0-39: Candidate lacks most of the required hard skills for this role

For strengths: cite specific hard skills, tools, or technical experiences from the candidate's profile that match job requirements.
For gaps: cite specific hard skills, technologies, or tools mentioned in the job listings that are absent from the candidate's profile.
For suggestions: give concrete, actionable steps to close the technical gaps (e.g. "Build a project using X", "Get certified in Y", "Learn Z through a hands-on course").

Candidate profile:
{resume_json}

Job listings:
{jobs_json}
```

---

### Learning Roadmap Prompt (`ROADMAP_PROMPT`)

Sent to `gpt-4o-mini` at `temperature=0.2`. `{persona_context}` is the persona string or empty. `{gaps}` is the gap list as a bulleted string.

```
You are a career coach AI. Based on the skill gaps below for the role of "{job_title}", generate a personalized learning roadmap and return ONLY a valid JSON array with no markdown or extra text.

Return this exact structure:
[
  {
    "skill": "<skill this resource addresses>",
    "resource": "<specific course, project, or certification name>",
    "provider": "<e.g. Coursera, YouTube, freeCodeCamp, LeetCode, official docs>",
    "type": "<course | project | certification>",
    "cost": "<free | paid>",
    "time_estimate": "<e.g. 2 hours, 1 week, 3 months>",
    "timeframe": "<short-term | medium-term | long-term>"
  },
  ...
]

Timeframe definitions:
- short-term: can be completed in 1 week or less
- medium-term: 1 week to 1 month
- long-term: more than 1 month

Rules:
- Suggest 1-2 resources per gap, prioritising free resources where possible
- Be specific: use real course/resource names (e.g. "CS50's Introduction to AI with Python" not just "an AI course")
- Include at least one hands-on project suggestion per major gap
- Order items by timeframe (short-term first)

{persona_context}

Skill gaps to address:
{gaps}
```

---

## Design Decisions & Tradeoffs

### Single batch call for job extraction

Rather than calling OpenAI once per job, all N raw job descriptions are sent in a single prompt. This reduces latency (one round-trip vs. N) and cost. The tradeoff is that a single model failure aborts all extractions at once — mitigated by the `_fallback_job()` function, which reconstructs each job directly from the raw JSearch response if the batch call fails or returns fewer items than expected.

### Company and apply link come from JSearch, not OpenAI

After the batch extraction, `company` and `apply_link` are overwritten with values from the original `JSearch` data. The model is good at summarising descriptions and consolidating qualifications but is unnecessary for copying a company name or URL verbatim — and introduces transcription errors when asked to do so. Keeping the model focused on what it is good at (synthesis and reformatting) and using the source API for authoritative fields is more reliable.

### Hard-skills-only gap analysis

The scoring prompt explicitly instructs the model to ignore all soft skills. In practice, language models tend to pad gap analysis with soft-skill observations ("improve communication") that are not actionable for a job seeker and dilute the signal-to-noise ratio of the output. Restricting to hard skills makes every bullet in the strengths, gaps, and suggestions sections concrete and addressable.

### Implicit skill extraction

The gap analysis prompt instructs the model to extract hard skills from project and work experience _descriptions_, not just the explicit skills list. This is important for resumes where the skills section is sparse but the project descriptions demonstrate hands-on use of relevant technologies. Without this instruction the model systematically under-scores candidates whose resume structure buries skills in narrative text.

### `temperature=0` for structured outputs, `temperature=0.2` for roadmap

Parsing, extraction, and analysis tasks require consistent JSON structure — deterministic output (`temperature=0`) minimises the chance of structural variation. The roadmap benefits from slight creativity (`temperature=0.2`) to generate varied resource suggestions rather than the same handful of popular courses for every user.

### Concurrent Brave Search with Semaphore

Roadmap generation can produce 10–20 items, each requiring a URL lookup. Running these sequentially would add 10–20 seconds of latency. Using `asyncio.gather` with a `Semaphore(5)` fires all requests concurrently while respecting Brave's per-second rate limit. A failed URL fetch is silently swallowed (the item is returned without a URL) so that a single rate-limit spike doesn't break the entire roadmap.

### Persona as a context injection, not a separate model

Rather than maintaining different prompts per persona or fine-tuning separate models, persona behaviour is implemented as a short paragraph prepended to the existing prompt. This is sufficient for the three distinct behaviours needed (standard, graduate-friendly, switcher-friendly) and requires no additional API keys or model deployments. The tradeoff is that the persona context competes for attention with the rest of the prompt — for more nuanced personas or stricter behavioural constraints, a separate system prompt or dedicated fine-tune would be the next step.

### Server-side OAuth rather than a client-side library

The Google OAuth flow runs entirely in the FastAPI backend (redirect → code exchange → JWT issuance). This avoids shipping any Google OAuth JS SDK to the Streamlit frontend and keeps credentials server-side only. The Streamlit client receives a single short-lived opaque JWT; it never sees the Google access token.

### Roadmap completion state merge

When a user re-generates the roadmap (e.g. after editing their resume), `save_roadmap` fetches existing roadmap docs first and preserves any `completed=True` flags on items that share the same `skill` name. This prevents the frustrating UX of losing progress on checked-off items just because the roadmap was regenerated.

### Job Search before Resume Upload

The wizard flow was changed from Resume → Jobs to Jobs → Resume. Job search is fast (seconds), while resume upload requires the user to have a PDF on hand. Starting with job search lets users see relevant listings immediately and understand the role landscape before deciding which resume to upload — reducing drop-off at the first step.

### JSearch `date_posted: "week"` filter

Without this filter, JSearch returns a mix of fresh and stale listings, some of which are several months old and may no longer be accepting applications. Filtering to the past week keeps the job cards relevant and the Apply Now links live.

---

## Technologies Used

| Package / Service | Category | How we used it | Why we chose it |
|---|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | Framework | Powers the entire backend — exposes REST endpoints for auth, resume parsing, job search, gap analysis, roadmap generation, and search CRUD | Native `async`/`await` is required for concurrent Brave Search lookups and non-blocking Firestore writes; cleaner than Flask for async workloads |
| [Streamlit](https://streamlit.io/) | Framework | Builds the entire frontend UI as a 4-step wizard with session state, file upload, interactive form controls, and a search dashboard | Lets the UI be written entirely in Python without any HTML/CSS/JS; `st.session_state` maps naturally to the step-by-step flow |
| [Uvicorn](https://www.uvicorn.org/) | Framework | ASGI server that runs the FastAPI app | Standard production-grade server for FastAPI; supports `--reload` for development |
| [Firebase Admin SDK](https://firebase.google.com/docs/admin/setup) | Package | Reads and writes all user, search, job, resume, analysis, and roadmap data to Cloud Firestore | Official server-side SDK; no additional auth setup needed when using a service account; gRPC transport is fast for structured document writes |
| [python-jose](https://github.com/mpdavis/python-jose) | Package | Signs and verifies HS256 JWTs for user sessions | Lightweight, well-tested JWT library; no external service required for token issuance |
| [google-auth-oauthlib](https://github.com/googleapis/google-auth-library-python-oauthlib) | Package | Assists with OAuth 2.0 scope validation | Provides Google-specific scope constants without pulling in a heavier client library |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | Package | Extracts raw text from every page of the uploaded PDF resume before sending it to the model | More reliable text extraction than PyPDF2 on complex resume layouts; returns plain strings with no extra configuration |
| [httpx](https://www.python-httpx.org/) | Package | Makes async HTTP calls to Google OAuth endpoints, the JSearch API, and Brave Search inside FastAPI route handlers | Drop-in async HTTP client; works natively with `asyncio.gather` and FastAPI's event loop |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | Package | Loads all secrets from the `.env` file at startup | Keeps credentials out of source code with zero boilerplate |
| [openai](https://github.com/openai/openai-python) | Package | Sends all prompts (resume parse, job extraction, gap analysis, roadmap) to the OpenAI Chat Completions API | Official SDK; handles auth, retries, and response parsing |
| [fpdf2](https://py-fpdf2.readthedocs.io/) | Package | Generates the demo resume PDFs (`generate_resumes.py`) | Lightweight pure-Python PDF writer; no external dependencies required to produce simple formatted documents |
| [gpt-4o-mini](https://platform.openai.com/docs/models/gpt-4o-mini) | Model | Runs all four AI tasks: resume parsing, job extraction, gap analysis, and roadmap generation | Strong instruction-following at low cost and low latency; `temperature=0` gives deterministic structured JSON outputs |
| [JSearch API](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) | API | Fetches real, recently-posted job listings by title via RapidAPI | Provides structured job data including description, qualifications, company, and an apply link without scraping |
| [Brave Search API](https://brave.com/search/api/) | API | Enriches each roadmap item with a real resource URL by querying `"{resource name} {provider}"` | Independent index returns fresh, unfiltered results; generous free tier; suitable for programmatic lookups |
| [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2) | API | Authenticates users via their Google account | No password management required; users already have Google accounts; consent screen provides a clear trust boundary |
| [Firebase Firestore](https://firebase.google.com/docs/firestore) | API | Stores all user data, search history, and AI results durably | Serverless NoSQL with a generous free tier; subcollection schema maps naturally to the search → jobs/resume/analysis/roadmap hierarchy |
| [OpenAI Platform](https://platform.openai.com/) | API | Hosts the gpt-4o-mini model accessed via the `openai` Python SDK | Reliable, well-documented API with predictable JSON output at `temperature=0` |

---

## Getting Started on a New Machine

### Prerequisites

- Python 3.10+
- A terminal (macOS/Linux) or WSL (Windows)
- API keys / credentials for:
  - [OpenAI](https://platform.openai.com/) (`OPENAI_API_KEY`)
  - [RapidAPI / JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) (`RAPIDAPI_KEY`)
  - [Brave Search API](https://api.search.brave.com/) (`BRAVE_API_KEY`)
  - [Google OAuth 2.0](https://console.cloud.google.com/) — Web application credentials with `http://localhost:8000/auth/callback` as an authorised redirect URI (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
  - [Firebase](https://console.firebase.google.com/) — A Firestore database (Native mode) and a service account JSON key (`FIREBASE_PROJECT_ID`, `firebase_service_account.json`)

### 1. Clone the repository

```bash
git clone https://github.com/nisar2/skillbridge.git
cd skillbridge
```

### 2. Create and activate a virtual environment

```bash
python3.10 -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows
```

### 3. Install dependencies

```bash
pip install fastapi uvicorn[standard] streamlit openai pdfplumber httpx python-dotenv fpdf2 \
            firebase-admin google-auth-oauthlib "python-jose[cryptography]"
```

### 4. Place the Firebase service account key

Download the JSON key from **Firebase Console → Project Settings → Service Accounts → Generate new private key** and save it as:

```
skillbridge/firebase_service_account.json
```

This file is listed in `.gitignore` and must never be committed.

### 5. Configure environment variables

Create a `.env` file in the project root:

```bash
cat > .env << 'EOF'
OPENAI_API_KEY=sk-...
RAPIDAPI_KEY=...
BRAVE_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
FIREBASE_PROJECT_ID=...
JWT_SECRET=<output of: python -c "import secrets; print(secrets.token_hex(32))">
STREAMLIT_URL=http://localhost:8501
BACKEND_URL=http://localhost:8000
EOF
```

Never commit `.env` to version control.

### 6. (Optional) Generate demo resume PDFs

```bash
python generate_resumes.py
```

This creates `demo/jamie_park_resume.pdf` (recent graduate) and `demo/rachel_okonkwo_resume.pdf` (career switcher).

### 7. Start the backend

In one terminal:

```bash
uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`. The `--reload` flag restarts the server on file changes.

### 8. Start the frontend

In a second terminal (with the virtualenv active):

```bash
streamlit run frontend/streamlit_app.py
```

Streamlit will open `http://localhost:8501` in your browser automatically.

### 9. Sign in

Navigate to `http://localhost:8501`. Click **Sign in with Google** and authenticate with an account that has been added as a test user in the Google OAuth consent screen (**Google Cloud Console → APIs & Services → OAuth consent screen → Test users**).

After consent, Google redirects to `http://localhost:8000/auth/callback`, which issues a JWT and redirects back to Streamlit. You will land on the search dashboard.

### 10. Demo walkthrough

| Step | Action | Recommended file / setting |
|------|--------|---------------------------|
| 1 | Search for jobs | "Data Scientist" or "Machine Learning Engineer", 3–5 listings |
| 2 | Upload resume PDF | `demo/jamie_park_resume.pdf` with **🎓 Recent Graduate** persona, or `demo/rachel_okonkwo_resume.pdf` with **🔄 Career Switcher** persona |
| 3 | Run gap analysis | Click **Analyse My Profile** |
| 4 | Generate roadmap | Click **Generate Learning Roadmap** |

### Project structure

```
skillbridge/
├── backend/
│   ├── main.py              # FastAPI app — all routes (auth, AI, search CRUD)
│   ├── auth.py              # Google OAuth flow + JWT helpers + FastAPI dependencies
│   └── firestore_db.py      # All Firestore read/write helpers
├── frontend/
│   └── streamlit_app.py     # Streamlit UI — login, dashboard, 4-step wizard
├── demo/
│   ├── jamie_park_resume.pdf
│   └── rachel_okonkwo_resume.pdf
├── generate_resumes.py      # Script to regenerate demo PDFs
├── logo.png                 # App logo (displayed in sidebar)
├── firebase_service_account.json  # Firebase credentials (not committed)
├── .env                     # API keys and secrets (not committed)
└── README.md
```

