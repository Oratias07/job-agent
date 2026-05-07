"""Scraper for Microsoft Careers global site — uses the public search REST API."""

import hashlib
import logging
import requests

logger = logging.getLogger(__name__)

# Microsoft's public careers search API (no Playwright needed)
API_URL = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
JOB_BASE_URL = "https://jobs.careers.microsoft.com/global/en/job/"

KEYWORDS = ["student", "intern", "internship", "סטודנט", "התמחות"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def scrape() -> list[dict]:
    """Return list of job dicts from Microsoft Careers global."""
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for keyword in ["intern", "student"]:
        try:
            params = {
                "q": keyword,
                "lc": "Israel",
                "l": "en_us",
                "pg": "1",
                "pgSz": "20",
                "o": "Relevance",
                "flt": "true",
            }
            resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Microsoft Careers: API request failed for query '%s'", keyword)
            continue

        for posting in data.get("operationResult", {}).get("result", {}).get("jobs", []):
            title = posting.get("title", "").strip()
            job_id_raw = str(posting.get("jobId", ""))
            description = posting.get("description", "").strip()
            location = posting.get("location", "").strip()

            # Filter to Israel only
            loc_lower = location.lower()
            if location and "israel" not in loc_lower and "tel aviv" not in loc_lower:
                continue

            if not _matches_keywords(title + " " + description):
                continue

            url = f"{JOB_BASE_URL}{job_id_raw}" if job_id_raw else ""
            job_id = (
                f"mscareer-{job_id_raw}"
                if job_id_raw
                else f"mscareer-{hashlib.md5((title + url).encode()).hexdigest()[:8]}"
            )

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            jobs.append({
                "id": job_id,
                "title": title,
                "company": "Microsoft",
                "url": url or "https://jobs.careers.microsoft.com",
                "description": f"{location}\n{description}".strip(),
            })

    logger.info("Microsoft Careers: found %d matching jobs", len(jobs))
    return jobs
