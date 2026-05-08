from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import tempfile
import os
import json
import re
import logging
import asyncio
import httpx
import pdfplumber
from openai import OpenAI
from dotenv import load_dotenv

from backend.auth import (
    get_current_user,
    get_optional_user,
    build_google_auth_redirect,
    handle_google_callback,
)
from backend.firestore_db import (
    get_user_searches,
    create_search,
    save_jobs,
    get_jobs,
    save_resume,
    get_resume,
    save_analysis,
    get_analysis,
    save_roadmap,
    get_roadmap,
    toggle_roadmap_item,
)

logging.basicConfig(level=logging.INFO)

load_dotenv(override=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

# Allow CORS for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/auth/google")
async def google_login():
    return build_google_auth_redirect()


@app.get("/auth/callback")
async def google_callback(code: str, state: str):
    return await handle_google_callback(code, state)


@app.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return JSONResponse(content=current_user)


# ---------------------------------------------------------------------------
# Search CRUD routes
# ---------------------------------------------------------------------------

class CreateSearchRequest(BaseModel):
    job_title: str


@app.get("/searches")
async def list_searches(current_user: dict = Depends(get_current_user)):
    searches = await get_user_searches(current_user["uid"])
    return JSONResponse(content=searches)


@app.post("/searches")
async def create_search_route(
    body: CreateSearchRequest,
    current_user: dict = Depends(get_current_user),
):
    search_id = await create_search(current_user["uid"], body.job_title)
    return JSONResponse(content={"search_id": search_id, "job_title": body.job_title})


@app.get("/searches/{search_id}/jobs")
async def get_search_jobs(search_id: str, current_user: dict = Depends(get_current_user)):
    jobs = await get_jobs(current_user["uid"], search_id)
    return JSONResponse(content=jobs)


@app.get("/searches/{search_id}/resume")
async def get_search_resume(search_id: str, current_user: dict = Depends(get_current_user)):
    resume = await get_resume(current_user["uid"], search_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="No resume saved for this search.")
    return JSONResponse(content=resume)


@app.get("/searches/{search_id}/analysis")
async def get_search_analysis(search_id: str, current_user: dict = Depends(get_current_user)):
    analysis = await get_analysis(current_user["uid"], search_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="No analysis saved for this search.")
    return JSONResponse(content=analysis)


@app.get("/searches/{search_id}/roadmap")
async def get_search_roadmap(search_id: str, current_user: dict = Depends(get_current_user)):
    roadmap = await get_roadmap(current_user["uid"], search_id)
    return JSONResponse(content=roadmap)


class ToggleRoadmapItemRequest(BaseModel):
    completed: bool


@app.patch("/searches/{search_id}/roadmap/{item_id}")
async def patch_roadmap_item(
    search_id: str,
    item_id: str,
    body: ToggleRoadmapItemRequest,
    current_user: dict = Depends(get_current_user),
):
    await toggle_roadmap_item(current_user["uid"], search_id, item_id, body.completed)
    return JSONResponse(content={"ok": True})


class SaveJobsRequest(BaseModel):
    jobs: list


@app.put("/searches/{search_id}/jobs")
async def put_search_jobs(
    search_id: str,
    body: SaveJobsRequest,
    current_user: dict = Depends(get_current_user),
):
    await save_jobs(current_user["uid"], search_id, body.jobs)
    return JSONResponse(content={"ok": True})


class SaveResumeRequest(BaseModel):
    resume: dict


@app.put("/searches/{search_id}/resume")
async def put_search_resume(
    search_id: str,
    body: SaveResumeRequest,
    current_user: dict = Depends(get_current_user),
):
    await save_resume(current_user["uid"], search_id, body.resume)
    return JSONResponse(content={"ok": True})


RESUME_PARSE_PROMPT = """
You are a resume parser. Extract the following structured information from the resume text below and return ONLY valid JSON with no markdown or extra text.

Return this exact structure:
{{
  "projects": [
    {{"title": "...", "description": "..."}}
  ],
  "work_experience": [
    {{"title": "...", "description": "..."}}
  ],
  "skills": ["skill1", "skill2", "..."]
}}

Rules:
- "title" for work_experience should be the job title and company (e.g. "Software Engineer at Acme Corp")
- "description" should be a concise summary of responsibilities/achievements
- "skills" should be a flat list of individual skills (technologies, languages, tools, soft skills)
- If a section is missing from the resume, return an empty list for it

Resume text:
{resume_text}
"""

@app.post("/parse_resume")
async def parse_resume(
    file: UploadFile = File(...),
    search_id: Optional[str] = Query(None),
    user: Optional[dict] = Depends(get_optional_user),
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save uploaded PDF to a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # Extract text from PDF
        with pdfplumber.open(tmp_path) as pdf:
            resume_text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            ).strip()

        if not resume_text:
            raise HTTPException(status_code=422, detail="Could not extract text from the PDF. Please ensure it is not a scanned image.")

        # Send to OpenAI for structured parsing
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": RESUME_PARSE_PROMPT.format(resume_text=resume_text),
                }
            ],
            temperature=0,
        )

        raw = completion.choices[0].message.content
        logging.info("OpenAI raw response: %r", raw)
        if not raw:
            raise HTTPException(status_code=500, detail="OpenAI returned an empty response.")
        # Robustly extract JSON object regardless of surrounding text or markdown fences
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise HTTPException(status_code=500, detail=f"Could not find JSON in OpenAI response: {raw[:200]}")
        parsed = json.loads(match.group(0))

    except json.JSONDecodeError as e:
        logging.error("JSON decode error: %s", e)
        raise HTTPException(status_code=500, detail=f"OpenAI returned an unexpected format: {e}")
    except Exception as e:
        logging.error("Error parsing resume: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.remove(tmp_path)

    if user and search_id:
        await save_resume(user["uid"], search_id, parsed)

    return JSONResponse(content=parsed)


JOB_EXTRACT_PROMPT = """
You are a job description parser. Given the list of raw job postings below, extract structured data for ALL of them and return ONLY a valid JSON array with no markdown or extra text.

Return this exact structure (an array, one object per job):
[
  {{
    "title": "...",
    "description": "...",
    "qualifications": ["...", "..."]
  }},
  ...
]

Rules:
- "title" is the job title
- "description" is a 2-3 sentence summary of the role
- "qualifications" is a combined list of all required and preferred skills and experience
- Return exactly {n} objects in the array, one per job posting below

Job postings:
{jobs_text}
"""


def _build_job_text(job: dict, index: int) -> str:
    highlights = job.get("job_highlights") or {}
    highlight_quals = highlights.get("Qualifications") or []

    required_skills = job.get("job_required_skills") or []

    exp = job.get("job_required_experience") or {}
    exp_parts = []
    if exp.get("required_experience_in_months"):
        years = exp["required_experience_in_months"] // 12
        if years:
            exp_parts.append(f"{years}+ years of experience required")
    if exp.get("experience_mentioned"):
        exp_parts.append("experience required")

    quals_lines = highlight_quals + required_skills + exp_parts
    qualifications = "\n".join(quals_lines)

    return (
        f"--- Job {index + 1} ---\n"
        f"Title: {job.get('job_title', '')}\n"
        f"Company: {job.get('employer_name', '')}\n"
        f"Description: {(job.get('job_description', '') or '')[:3000]}\n"
        f"Qualifications:\n{qualifications}\n"
    )


def _fallback_job(job: dict) -> dict:
    highlights = job.get("job_highlights") or {}
    return {
        "title": job.get("job_title", "Unknown"),
        "company": job.get("employer_name", ""),
        "description": (job.get("job_description", "") or "")[:500],
        "qualifications": (highlights.get("Qualifications") or []) + (job.get("job_required_skills") or []),
        "apply_link": job.get("job_apply_link") or job.get("job_google_link", ""),
    }


@app.post("/fetch_jobs")
async def fetch_jobs(
    job_title: str = Query(..., description="Job title to search for"),
    n: int = Query(2, ge=1, le=10, description="Number of job listings to fetch"),
    search_id: Optional[str] = Query(None),
    user: Optional[dict] = Depends(get_optional_user),
):
    rapidapi_key = os.getenv("RAPIDAPI_KEY")
    if not rapidapi_key:
        raise HTTPException(status_code=500, detail="RAPIDAPI_KEY not configured.")

    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {"query": job_title, "page": "1", "num_pages": "1", "date_posted": "week"}

    async with httpx.AsyncClient() as http:
        resp = await http.get(
            "https://jsearch.p.rapidapi.com/search",
            headers=headers,
            params=params,
            timeout=15,
        )

    logging.info("JSearch status: %s, body: %s", resp.status_code, resp.text[:300])

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"JSearch API error: {resp.text[:200]}")

    raw_jobs = resp.json().get("data", [])[:n]
    if not raw_jobs:
        raise HTTPException(status_code=404, detail=f"No job listings found for '{job_title}'.")

    logging.info("JSearch raw jobs:\n%s", json.dumps(raw_jobs, indent=2))

    # Build all job texts and send to OpenAI in a single batch call
    jobs_text = "\n".join(_build_job_text(job, i) for i, job in enumerate(raw_jobs))
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": JOB_EXTRACT_PROMPT.format(n=len(raw_jobs), jobs_text=jobs_text),
            }],
            temperature=0,
        )
        raw = completion.choices[0].message.content
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON array found in OpenAI response")
        structured_jobs = json.loads(match.group(0))
        # Ensure we have the right count; fall back for any missing entries
        if len(structured_jobs) < len(raw_jobs):
            for i in range(len(structured_jobs), len(raw_jobs)):
                structured_jobs.append(_fallback_job(raw_jobs[i]))
    except Exception as e:
        logging.error("Batch job extraction failed, using fallback: %s", e)
        structured_jobs = [_fallback_job(job) for job in raw_jobs]

    # Merge company and apply link from raw JSearch data (authoritative source)
    for i, job in enumerate(structured_jobs):
        if i < len(raw_jobs):
            job["company"] = raw_jobs[i].get("employer_name", "")
            job["apply_link"] = raw_jobs[i].get("job_apply_link") or raw_jobs[i].get("job_google_link", "")

    if user and search_id:
        await save_jobs(user["uid"], search_id, structured_jobs)

    return JSONResponse(content=structured_jobs)


PERSONA_GAP_CONTEXTS = {
    "graduate": (
        "Persona note: This candidate is a recent graduate. "
        "Treat academic projects, coursework, and internships as equivalent to professional work experience. "
        "Weight the presence of relevant certifications highly in scoring."
    ),
    "switcher": (
        "Persona note: This candidate is switching careers from a different industry. "
        "Add a 'transferable_skills' array to the JSON output listing hard skills from their background that directly apply to this role. "
        "Recognise cross-industry technical skills (e.g. data analysis, scripting, cloud tools) as partial matches."
    ),
}

PERSONA_ROADMAP_CONTEXTS = {
    "graduate": (
        "Persona note: This candidate is a recent graduate. "
        "Prioritise certifications in the roadmap — they provide immediate, verifiable credibility for candidates with limited professional experience."
    ),
    "switcher": (
        "Persona note: This candidate is switching careers. "
        "Where possible, suggest resources that explicitly bridge their prior domain to the target role and build on their existing background."
    ),
}

GAP_ANALYSIS_PROMPT = """
You are a career coach AI. Compare the candidate's resume profile against a set of job descriptions for the role of "{job_title}" and return ONLY valid JSON with no markdown or extra text.

{persona_context}

Return this exact structure:
{{
  "score": <integer 0-100>,
  "summary": "<2-3 sentence overall assessment>",
  "strengths": ["<bullet 1>", "<bullet 2>", ...],
  "gaps": ["<bullet 1>", "<bullet 2>", ...],
  "suggestions": ["<bullet 1>", "<bullet 2>", ...]{transferable_skills_field}
}}

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
"""


class GapAnalysisRequest(BaseModel):
    resume: dict
    jobs: list
    job_title: str
    persona: str = "general"
    search_id: Optional[str] = None


@app.post("/gap_analysis")
async def gap_analysis(request: GapAnalysisRequest, user: Optional[dict] = Depends(get_optional_user)):
    persona = request.persona or "general"
    persona_context = PERSONA_GAP_CONTEXTS.get(persona, "")
    transferable_skills_field = (
        ',\n  "transferable_skills": ["<transferable skill 1>", "<transferable skill 2>", ...]'
        if persona == "switcher" else ""
    )
    try:
        prompt = GAP_ANALYSIS_PROMPT.format(
            job_title=request.job_title,
            resume_json=json.dumps(request.resume, indent=2),
            jobs_json=json.dumps(request.jobs, indent=2),
            persona_context=persona_context,
            transferable_skills_field=transferable_skills_field,
        )
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = completion.choices[0].message.content
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON found in OpenAI response: {raw[:200]}")
        result = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"OpenAI returned unexpected format: {e}")
    except Exception as e:
        logging.error("Gap analysis error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    if user and request.search_id:
        await save_analysis(user["uid"], request.search_id, {**result, "persona": request.persona})

    return JSONResponse(content=result)


ROADMAP_PROMPT = """
You are a career coach AI. Based on the skill gaps below for the role of "{job_title}", generate a personalized learning roadmap and return ONLY a valid JSON array with no markdown or extra text.

Return this exact structure:
[
  {{
    "skill": "<skill this resource addresses>",
    "resource": "<specific course, project, or certification name>",
    "provider": "<e.g. Coursera, YouTube, freeCodeCamp, LeetCode, official docs>",
    "type": "<course | project | certification>",
    "cost": "<free | paid>",
    "time_estimate": "<e.g. 2 hours, 1 week, 3 months>",
    "timeframe": "<short-term | medium-term | long-term>"
  }},
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
"""


class RoadmapRequest(BaseModel):
    gaps: list
    job_title: str
    persona: str = "general"
    search_id: Optional[str] = None


@app.post("/learning_roadmap")
async def learning_roadmap(request: RoadmapRequest, user: Optional[dict] = Depends(get_optional_user)):
    persona = request.persona or "general"
    persona_context = PERSONA_ROADMAP_CONTEXTS.get(persona, "")
    try:
        prompt = ROADMAP_PROMPT.format(
            job_title=request.job_title,
            gaps="\n".join(f"- {g}" for g in request.gaps),
            persona_context=persona_context,
        )
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        raw = completion.choices[0].message.content
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array in OpenAI response: {raw[:200]}")
        result = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"OpenAI returned unexpected format: {e}")
    except Exception as e:
        logging.error("Roadmap error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # Enrich each roadmap item with a real URL via Brave Search
    brave_key = os.getenv("BRAVE_API_KEY")
    if brave_key:
        sem = asyncio.Semaphore(3)  # max 5 concurrent Brave requests

        async def fetch_url(item: dict, http: httpx.AsyncClient) -> dict:
            query = f"{item.get('resource', '')} {item.get('provider', '')}"
            async with sem:
                try:
                    resp = await http.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
                        params={"q": query, "count": 1},
                        timeout=6,
                    )
                    if resp.status_code == 200:
                        results = resp.json().get("web", {}).get("results", [])
                        if results:
                            item["url"] = results[0].get("url", "")
                except Exception as e:
                    logging.warning("Brave search failed for '%s': %s", query, e)
            return item

        async with httpx.AsyncClient() as http:
            result = await asyncio.gather(*[fetch_url(item, http) for item in result])
        result = list(result)

    if user and request.search_id:
        saved = await save_roadmap(user["uid"], request.search_id, list(result), request.persona)
        result = saved

    return JSONResponse(content=result)
