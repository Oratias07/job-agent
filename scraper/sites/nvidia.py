"""Scraper for NVIDIA Careers — prefers the REST API, falls back to Playwright."""

import hashlib
import logging
import requests
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# NVIDIA's career site exposes a REST API behind the scenes
API_URL = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"

BROWSE_URL = (
    "https://jobs.nvidia.com/careers"
    "?query=Student+Intern&start=0&location=Israel&pid=893391945660"
    "&sort_by=relevance&filter_include_remote=1"
)

KEYWORDS = ["student", "intern", "סטודנט", "התמחות", "internship"]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def _scrape_api() -> list[dict]:
    """Try NVIDIA's Workday REST API — searches for both 'Student' and 'Intern'."""
    headers = {"Content-Type": "application/json"}
    seen_ids: set[str] = set()
    jobs: list[dict] = []

    for search_term in ["student", "intern", "Student", "Intern"]:
        payload = {
            "appliedFacets": {"locationCountry": ["bc33aa3152ec42d4995f4791a106ed09"]},  # Israel
            "limit": 20,
            "offset": 0,
            "searchText": search_term,
        }
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        if not resp.ok:
            logger.debug("NVIDIA API returned %s for searchText=%r — skipping", resp.status_code, search_term)
            continue
        data = resp.json()

        for posting in data.get("jobPostings", []):
            title = posting.get("title", "")
            bullet_fields = posting.get("bulletFields", [])
            description = " ".join(bullet_fields) + " " + title
            external_path = posting.get("externalPath", "")
            url = (
                f"https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite{external_path}"
                if external_path else BROWSE_URL
            )

            if not _matches_keywords(title + " " + description):
                continue

            # Stable ID: use the Workday path slug when available
            job_id = (
                f"nvidia-{external_path.strip('/').split('/')[-1]}"
                if external_path
                else f"nvidia-{hashlib.md5(title.encode()).hexdigest()[:8]}"
            )

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            jobs.append({
                "id": job_id,
                "title": title,
                "company": "NVIDIA",
                "url": url,
                "description": description,
            })

    return jobs


def _scrape_playwright() -> list[dict]:
    """Fallback: render NVIDIA's careers page with Playwright."""
    jobs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BROWSE_URL, timeout=60000)
        page.wait_for_timeout(5000)

        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

        # NVIDIA's job site uses anchor tags with href containing '/careers/job'
        job_links = page.query_selector_all("a[href*='/careers/job']")
        seen_hrefs: set[str] = set()
        for a in job_links:
            try:
                href = a.get_attribute("href") or ""
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                title_text = a.inner_text().strip()
                # The link element may contain the job ID and location as extra text;
                # take only the first non-empty line as the title
                title_text = next((ln.strip() for ln in title_text.splitlines() if ln.strip()), title_text)

                if not title_text or len(title_text) < 5:
                    continue

                if not _matches_keywords(title_text):
                    continue

                if not href.startswith("http"):
                    href = f"https://jobs.nvidia.com{href}"

                # Extract numeric job ID from path
                slug = href.rstrip("/").split("/")[-1]
                job_id = f"nvidia-{slug}"
                jobs.append({
                    "id": job_id,
                    "title": title_text,
                    "company": "NVIDIA",
                    "url": href,
                    "description": title_text,
                })
            except Exception:
                logger.debug("Failed to parse a job link on NVIDIA", exc_info=True)

        browser.close()
    return jobs


def scrape() -> list[dict]:
    """Return list of job dicts, preferring API over browser scraping."""
    try:
        jobs = _scrape_api()
        logger.info("NVIDIA (API): found %d matching jobs", len(jobs))
        return jobs
    except Exception:
        logger.warning("NVIDIA API failed, falling back to Playwright", exc_info=True)

    try:
        jobs = _scrape_playwright()
        logger.info("NVIDIA (Playwright): found %d matching jobs", len(jobs))
        return jobs
    except Exception:
        logger.exception("NVIDIA Playwright scrape also failed")
        return []
