"""
Firestore helpers for Skill-Bridge.

Document layout:
  users/{uid}
  users/{uid}/searches/{search_id}
  users/{uid}/searches/{search_id}/jobs/{job_id}
  users/{uid}/searches/{search_id}/resume          (single doc id="data")
  users/{uid}/searches/{search_id}/analysis        (single doc id="data")
  users/{uid}/searches/{search_id}/roadmap/{item_id}

All write operations are synchronous (firebase-admin uses gRPC under the hood).
They are called from async FastAPI route handlers using asyncio.to_thread so
the event loop is not blocked.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firebase init (lazy — only runs once)
# ---------------------------------------------------------------------------
_db = None


def _get_db():
    global _db
    if _db is not None:
        return _db

    import firebase_admin
    from firebase_admin import credentials, firestore

    key_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY_PATH", "firebase_service_account.json")

    if not firebase_admin._apps:
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
        else:
            # Fallback: use Application Default Credentials (e.g. on GCP)
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)

    _db = firestore.client()
    return _db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

async def upsert_user(uid: str, data: dict) -> None:
    import asyncio
    def _write():
        db = _get_db()
        ref = db.collection("users").document(uid)
        doc = ref.get()
        if doc.exists:
            ref.update({"name": data["name"], "photo_url": data["photo_url"]})
        else:
            ref.set({**data, "created_at": _now()})
    await asyncio.to_thread(_write)


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------

async def get_user_searches(uid: str) -> list[dict]:
    import asyncio
    def _read():
        db = _get_db()
        docs = (
            db.collection("users").document(uid)
            .collection("searches")
            .order_by("updated_at", direction="DESCENDING")
            .stream()
        )
        results = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            results.append(d)
        return results
    return await asyncio.to_thread(_read)


async def create_search(uid: str, job_title: str) -> str:
    import asyncio
    def _write():
        db = _get_db()
        now = _now()
        ref = (
            db.collection("users").document(uid)
            .collection("searches")
            .document()  # auto-ID
        )
        ref.set({
            "job_title": job_title,
            "created_at": now,
            "updated_at": now,
            "score": None,
        })
        return ref.id
    return await asyncio.to_thread(_write)


async def get_search(uid: str, search_id: str) -> Optional[dict]:
    import asyncio
    def _read():
        db = _get_db()
        doc = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .get()
        )
        if not doc.exists:
            return None
        d = doc.to_dict()
        d["id"] = doc.id
        return d
    return await asyncio.to_thread(_read)


async def _touch_search(uid: str, search_id: str) -> None:
    """Update the updated_at timestamp on the parent search document."""
    import asyncio
    def _write():
        db = _get_db()
        db.collection("users").document(uid).collection("searches").document(search_id).update(
            {"updated_at": _now()}
        )
    await asyncio.to_thread(_write)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

async def save_jobs(uid: str, search_id: str, jobs: list[dict]) -> None:
    """Replace all jobs in a search with the provided list."""
    import asyncio
    def _write():
        db = _get_db()
        col = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("jobs")
        )
        # Delete existing job docs
        for existing in col.stream():
            existing.reference.delete()
        # Write new ones
        for job in jobs:
            col.document().set({**job, "added_at": _now()})
    await asyncio.to_thread(_write)
    await _touch_search(uid, search_id)


async def append_jobs(uid: str, search_id: str, jobs: list[dict]) -> None:
    """Add new jobs to an existing search without deleting current ones."""
    import asyncio
    def _write():
        db = _get_db()
        col = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("jobs")
        )
        for job in jobs:
            col.document().set({**job, "added_at": _now()})
    await asyncio.to_thread(_write)
    await _touch_search(uid, search_id)


async def get_jobs(uid: str, search_id: str) -> list[dict]:
    import asyncio
    def _read():
        db = _get_db()
        docs = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("jobs")
            .order_by("added_at")
            .stream()
        )
        results = []
        for doc in docs:
            d = doc.to_dict()
            d["_doc_id"] = doc.id
            results.append(d)
        return results
    return await asyncio.to_thread(_read)


async def delete_all_jobs(uid: str, search_id: str) -> None:
    import asyncio
    def _write():
        db = _get_db()
        col = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("jobs")
        )
        for doc in col.stream():
            doc.reference.delete()
    await asyncio.to_thread(_write)
    await _touch_search(uid, search_id)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

async def save_resume(uid: str, search_id: str, resume: dict) -> None:
    import asyncio
    def _write():
        db = _get_db()
        db.collection("users").document(uid).collection("searches").document(search_id).collection("resume").document("data").set(
            {**resume, "uploaded_at": _now()}
        )
    await asyncio.to_thread(_write)
    await _touch_search(uid, search_id)


async def get_resume(uid: str, search_id: str) -> Optional[dict]:
    import asyncio
    def _read():
        doc = (
            _get_db()
            .collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("resume").document("data")
            .get()
        )
        return doc.to_dict() if doc.exists else None
    return await asyncio.to_thread(_read)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

async def save_analysis(uid: str, search_id: str, analysis: dict) -> None:
    import asyncio
    score = analysis.get("score")
    def _write():
        db = _get_db()
        now = _now()
        # Upsert analysis sub-doc
        db.collection("users").document(uid).collection("searches").document(search_id).collection("analysis").document("data").set(
            {**analysis, "updated_at": now}
        )
        # Denormalise score to parent search for dashboard display
        if score is not None:
            db.collection("users").document(uid).collection("searches").document(search_id).update(
                {"score": score, "updated_at": now}
            )
    await asyncio.to_thread(_write)


async def get_analysis(uid: str, search_id: str) -> Optional[dict]:
    import asyncio
    def _read():
        doc = (
            _get_db()
            .collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("analysis").document("data")
            .get()
        )
        return doc.to_dict() if doc.exists else None
    return await asyncio.to_thread(_read)


# ---------------------------------------------------------------------------
# Roadmap
# ---------------------------------------------------------------------------

async def save_roadmap(uid: str, search_id: str, new_items: list[dict], persona: str) -> list[dict]:
    """Write roadmap items, preserving completed state for items that reappear.

    Matching key: (skill, resource) pair — case-insensitive.
    Returns the merged list as saved to Firestore.
    """
    import asyncio

    def _item_key(item: dict) -> tuple:
        return (
            (item.get("skill") or "").lower().strip(),
            (item.get("resource") or "").lower().strip(),
        )

    def _write():
        db = _get_db()
        col = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("roadmap")
        )

        # Load existing items to preserve completion state
        existing_by_key: dict[tuple, dict] = {}
        for doc in col.stream():
            d = doc.to_dict()
            existing_by_key[_item_key(d)] = d

        # Delete all existing docs
        for doc in col.stream():
            doc.reference.delete()

        # Write merged items
        saved = []
        now = _now()
        for item in new_items:
            key = _item_key(item)
            prev = existing_by_key.get(key, {})
            merged = {
                **item,
                "completed": prev.get("completed", False),
                "completed_at": prev.get("completed_at", None),
                "persona": persona,
                "created_at": prev.get("created_at", now),
                "updated_at": now,
            }
            ref = col.document()
            ref.set(merged)
            merged["id"] = ref.id
            saved.append(merged)
        return saved

    result = await asyncio.to_thread(_write)
    await _touch_search(uid, search_id)
    return result


async def get_roadmap(uid: str, search_id: str) -> list[dict]:
    import asyncio
    def _read():
        db = _get_db()
        timeframe_order = {"short-term": 0, "medium-term": 1, "long-term": 2}
        docs = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("roadmap")
            .stream()
        )
        results = []
        for doc in docs:
            d = doc.to_dict()
            d["id"] = doc.id
            results.append(d)
        results.sort(key=lambda x: timeframe_order.get(x.get("timeframe", ""), 99))
        return results
    return await asyncio.to_thread(_read)


async def toggle_roadmap_item(uid: str, search_id: str, item_id: str, completed: bool) -> None:
    import asyncio
    def _write():
        db = _get_db()
        ref = (
            db.collection("users").document(uid)
            .collection("searches").document(search_id)
            .collection("roadmap").document(item_id)
        )
        ref.update({
            "completed": completed,
            "completed_at": _now() if completed else None,
        })
    await asyncio.to_thread(_write)
