"""Scraper for Monday.com Careers Israel — uses Lever ATS public API."""

import logging
import requests

logger = logging.getLogger(__name__)

LEVER_API = "https://api.lever.co/v0/postings/monday"
FALLBACK_URL = "https://monday.com/jobs"

KEYWORDS = ["student", "intern", "internship", "part-time", "part time",
            "junior", "associate", "סטודנט", "התמחות"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts from Monday.com Careers Israel."""
    jobs: list[dict] = []

    try:
        resp = requests.get(LEVER_API, headers=HEADERS, timeout=30, params={"mode": "json"})
        resp.raise_for_status()
        postings = resp.json()
    except Exception:
        logger.exception("Monday.com: Lever API failed")
        return jobs

    for posting in postings:
        title = posting.get("text", "").strip()
        categories = posting.get("categories", {})
        location = categories.get("location", "") if isinstance(categories, dict) else ""
        apply_url = posting.get("hostedUrl", "") or posting.get("applyUrl", "")
        job_id_raw = posting.get("id", "")

        # Only Israel locations
        loc_lower = location.lower()
        if location and "israel" not in loc_lower and "tel aviv" not in loc_lower and "haifa" not in loc_lower:
            continue

        lists = posting.get("lists", [])
        desc_text = " ".join(
            item.get("text", "") + " " + " ".join(item.get("content", []))
            for item in lists
            if isinstance(item, dict)
        )
        desc_text = desc_text[:800]

        full_text = title + " " + desc_text + " " + categories.get("team", "")
        if not _matches_keywords(full_text):
            continue

        job_id = f"monday-{job_id_raw}" if job_id_raw else f"monday-{title[:30]}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": "Monday.com",
            "url": apply_url or FALLBACK_URL,
            "description": f"{location}\n{desc_text}".strip(),
        })

    logger.info("Monday.com Careers: found %d matching jobs", len(jobs))
    return jobs
