"""
Telegram bot — accepts job URLs, replies with tailored CV + cover letter PDFs.

Usage:
    TELEGRAM_BOT_TOKEN=<token> GROQ_API_KEY=<key> python bot_listener.py

Send any message containing a job URL (http:// or https://) to the bot.
The bot will:
  1. Fetch and parse the job page
  2. Generate a tailored CV and cover letter via Groq
  3. Reply with both PDFs

Run this script on any machine (locally, a VPS, Railway, Render, etc.)
with the two env vars set.  It uses long-polling — no webhook/server needed.
"""

import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ── Project path ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from cv_agent.tailor import generate_tailored_cv, generate_cover_letter
from cv_agent.pdf_renderer import render_pdf

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
URL_RE = re.compile(r"https?://\S+")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── Telegram helpers ─────────────────────────────────────────────────────────

def _api(token: str, method: str, **kwargs) -> dict:
    url = TELEGRAM_API.format(token=token, method=method)
    resp = requests.post(url, timeout=60, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _send(token: str, chat_id: int, text: str) -> None:
    try:
        _api(token, "sendMessage", data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        })
    except Exception:
        logger.exception("Failed to send message to chat %s", chat_id)


def _send_pdf(token: str, chat_id: int, pdf_path: Path) -> None:
    try:
        with pdf_path.open("rb") as f:
            _api(token, "sendDocument",
                 data={"chat_id": chat_id},
                 files={"document": (pdf_path.name, f, "application/pdf")})
    except Exception:
        logger.exception("Failed to send PDF %s", pdf_path.name)


# ── Job page scraping ─────────────────────────────────────────────────────────

def _extract_with_requests(url: str) -> tuple[str, str, str]:
    """Fast path: plain HTTP fetch + BeautifulSoup."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_soup(soup, url)


def _extract_with_playwright(url: str) -> tuple[str, str, str]:
    """Slow path: render JS-heavy pages with Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
    soup = BeautifulSoup(html, "html.parser")
    return _parse_soup(soup, url)


def _parse_soup(soup: BeautifulSoup, url: str) -> tuple[str, str, str]:
    """Extract (title, company, description) from a BeautifulSoup document."""
    # ── Title ──
    title = ""
    # Prefer <title> or OG tags first
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
    if not title:
        page_title = soup.find("title")
        title = page_title.get_text(strip=True) if page_title else ""
    # Strip " - Company Name" suffixes from page titles
    title = re.split(r"\s*[|\-–—]\s*", title)[0].strip()

    # ── Company ──
    company = ""
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        company = og_site["content"].strip()
    if not company:
        # Try common patterns: "at Company", "@ Company", schema.org hiringOrganization
        hiring_org = soup.find(attrs={"itemprop": "hiringOrganization"})
        if hiring_org:
            company = hiring_org.get_text(strip=True)
    if not company:
        # Fallback to domain name
        company = urlparse(url).netloc.replace("www.", "").split(".")[0].capitalize()

    # ── Description ──
    # Remove boilerplate (nav, header, footer, scripts)
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Prefer the element with the most text that looks like a job description
    description = ""
    candidates = soup.find_all(
        ["div", "section", "article"],
        class_=re.compile(
            r"description|job-detail|job-body|content|posting|requisition|"
            r"vacancy|role|responsibilities|requirement",
            re.I,
        ),
    )
    if candidates:
        best = max(candidates, key=lambda el: len(el.get_text()))
        description = best.get_text(separator="\n", strip=True)

    if not description:
        # Broad fallback: main content area
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            description = main.get_text(separator="\n", strip=True)

    # Trim excessive whitespace lines
    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    description = "\n".join(lines[:300])  # cap at ~300 meaningful lines

    return title or "Unknown Title", company or "Unknown Company", description or "No description found."


def fetch_job_page(url: str) -> tuple[str, str, str]:
    """Return (title, company, description) for a job URL.

    Tries fast HTTP first; falls back to Playwright for JS-rendered pages.
    """
    try:
        return _extract_with_requests(url)
    except Exception as e:
        logger.info("Fast HTTP failed (%s), retrying with Playwright", e)
    return _extract_with_playwright(url)


# ── CV generation ─────────────────────────────────────────────────────────────

def generate_and_send_cv(token: str, chat_id: int, url: str) -> None:
    _send(token, chat_id, "⏳ Fetching job page...")

    try:
        title, company, description = fetch_job_page(url)
    except Exception as e:
        _send(token, chat_id, f"❌ Could not fetch the job page:\n<code>{e}</code>")
        return

    _send(
        token, chat_id,
        f"📋 <b>{_he(title)}</b>\n"
        f"🏢 {_he(company)}\n\n"
        f"⚙️ Generating tailored CV + cover letter..."
    )

    try:
        cv_md = generate_tailored_cv(title, company, description)
        cl_md = generate_cover_letter(title, company, description)
    except Exception as e:
        _send(token, chat_id, f"❌ CV generation failed:\n<code>{_he(str(e))}</code>")
        return

    safe_title = re.sub(r"[^A-Za-z0-9]+", "", title)[:40]
    safe_company = re.sub(r"[^A-Za-z0-9]+", "", company)[:30]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            cv_path = render_pdf(cv_md, tmp / f"OrAtias_CV_{safe_company}_{safe_title}.pdf")
            cl_path = render_pdf(cl_md, tmp / f"OrAtias_CoverLetter_{safe_company}_{safe_title}.pdf")
        except Exception as e:
            _send(token, chat_id, f"❌ PDF rendering failed:\n<code>{_he(str(e))}</code>")
            return

        _send(token, chat_id, "✅ Done! Sending PDFs...")
        _send_pdf(token, chat_id, cv_path)
        _send_pdf(token, chat_id, cl_path)

    logger.info("Sent CV + cover letter for '%s' at '%s'", title, company)


def _he(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Bot loop ──────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "👋 <b>Job CV Bot</b>\n\n"
    "Send me any job posting URL and I'll generate a tailored CV + cover letter for you.\n\n"
    "Example:\n"
    "<code>https://jobs.nvidia.com/jobs/XXXXX</code>"
)


def run(token: str) -> None:
    offset = 0
    logger.info("Bot started — waiting for job URLs...")

    while True:
        try:
            result = _api(token, "getUpdates", data={
                "offset": offset,
                "timeout": 30,  # long-poll
                "allowed_updates": ["message"],
            })
            updates = result.get("result", [])
        except requests.exceptions.Timeout:
            continue
        except Exception:
            logger.exception("getUpdates error — retrying in 5s")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            text = (msg.get("text") or "").strip()

            if not chat_id or not text:
                continue

            if text in ("/start", "/help"):
                _send(token, chat_id, HELP_TEXT)
                continue

            urls = URL_RE.findall(text)
            if not urls:
                _send(token, chat_id,
                      "📎 Please send a job posting URL (starting with http:// or https://)")
                continue

            # Process the first URL found
            generate_and_send_cv(token, chat_id, urls[0])


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable not set.")
        sys.exit(1)

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("ERROR: GROQ_API_KEY environment variable not set.")
        sys.exit(1)

    run(token)


if __name__ == "__main__":
    main()
