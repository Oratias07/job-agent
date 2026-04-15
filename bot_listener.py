"""
Telegram bot — accepts job URLs, replies with tailored CV + cover letter PDFs.

Each Telegram user stores their own CV in user_data/{chat_id}.json.
The bot prompts new users to upload their CV before processing any job URLs.

Usage:
    TELEGRAM_BOT_TOKEN=<token> GROQ_API_KEY=<key> python bot_listener.py

Send a job posting URL (http:// or https://) after registering your CV.
The bot will:
  1. Fetch and parse the job page
  2. Generate a tailored CV and cover letter via Groq
  3. Reply with both PDFs

Run this script on any machine with the two env vars set.
It uses long-polling — no webhook/server needed.
"""

import collections
import ipaddress
import json
import logging
import os
import re
import socket
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

# ── Project path ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from cv_agent.tailor import generate_tailored_cv, generate_cover_letter
from cv_agent.pdf_renderer import render_pdf

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_FILE_URL = "https://api.telegram.org/file/bot{token}/{file_path}"
URL_RE = re.compile(r"https?://\S+")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

USER_DATA_DIR = PROJECT_ROOT / "user_data"
MIN_CV_LENGTH = 100  # characters — anything shorter is rejected as too short
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# ── Concurrency ───────────────────────────────────────────────────────────────
# Worker threads: each user request runs in its own thread so the polling loop
# never blocks. Cap at 10 so Groq API parallelism stays manageable.
MAX_WORKERS = 10

# Playwright (Chromium) is memory-heavy (~150–200 MB per browser). Cap the
# number of simultaneous instances across all threads to avoid OOM.
MAX_PLAYWRIGHT_INSTANCES = 5
_playwright_sem = threading.Semaphore(MAX_PLAYWRIGHT_INSTANCES)

# Per-user file locks: prevent concurrent reads/writes to the same JSON file
# when a user sends two messages in rapid succession.
_user_locks: dict[int, threading.Lock] = {}
_user_locks_meta = threading.Lock()

def _get_user_lock(chat_id: int) -> threading.Lock:
    with _user_locks_meta:
        if chat_id not in _user_locks:
            _user_locks[chat_id] = threading.Lock()
        return _user_locks[chat_id]

# ── Rate limiting ────────────────────────────────────────────────────────────
_RATE_WINDOW = 60        # seconds
_RATE_MAX = 5            # max requests per window per user
_rate_buckets: dict[int, collections.deque] = {}
_rate_lock = threading.Lock()  # guards _rate_buckets across threads

def _check_rate_limit(chat_id: int) -> bool:
    """Return True if the user is within their rate limit, False if exceeded."""
    now = time.time()
    with _rate_lock:
        dq = _rate_buckets.setdefault(chat_id, collections.deque())
        while dq and now - dq[0] > _RATE_WINDOW:
            dq.popleft()
        if len(dq) >= _RATE_MAX:
            return False
        dq.append(now)
    return True

# ── SSRF protection ──────────────────────────────────────────────────────────
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

def _validate_url(url: str) -> None:
    """Raise ValueError if the URL targets a private/internal address (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// URLs are allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")
    if host.lower() in ("localhost", "0.0.0.0"):
        raise ValueError("Blocked host")
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname: {e}") from e
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            raise ValueError(f"URL resolves to a private/internal address ({ip}) — not allowed")

# ── Log sanitization ─────────────────────────────────────────────────────────
def _safe_log(s: str) -> str:
    """Remove newlines and control chars from untrusted strings going into logs."""
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(s))[:120]


# ── User data storage ─────────────────────────────────────────────────────────

def _load_user_data(chat_id: int) -> dict:
    path = USER_DATA_DIR / f"{chat_id}.json"
    with _get_user_lock(chat_id):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {"chat_id": chat_id}


def _save_user_data(data: dict) -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    chat_id = data["chat_id"]
    path = USER_DATA_DIR / f"{chat_id}.json"
    with _get_user_lock(chat_id):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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


def _he(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── File download & text extraction ──────────────────────────────────────────

def _download_telegram_file(token: str, file_id: str) -> bytes:
    file_info = _api(token, "getFile", data={"file_id": file_id})
    file_path = file_info["result"]["file_path"]
    url = TELEGRAM_FILE_URL.format(token=token, file_path=file_path)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except ImportError:
        raise RuntimeError(
            "pypdf is not installed. Please paste your CV as plain text instead."
        )
    except Exception as e:
        raise RuntimeError(f"Could not extract text from PDF: {e}") from e


def _extract_docx_text(docx_bytes: bytes) -> str:
    try:
        import io
        import docx
        doc = docx.Document(io.BytesIO(docx_bytes))
        return "\n".join(para.text for para in doc.paragraphs if para.text).strip()
    except ImportError:
        raise RuntimeError(
            "python-docx is not installed. Please paste your CV as plain text instead."
        )
    except Exception as e:
        raise RuntimeError(f"Could not extract text from docx: {e}") from e


# ── CV registration flow ──────────────────────────────────────────────────────

def _handle_start(token: str, chat_id: int, user_data: dict) -> None:
    if user_data.get("cv_text"):
        _send(token, chat_id,
              "👋 Your CV is already on file.\n\n"
              "Send me a job URL to get a tailored CV + cover letter.\n"
              "Use /updatecv to replace your stored CV.\n"
              "Use /help to see all options."
              + _PLAYWRIGHT_NOTE)
    else:
        user_data["awaiting_cv"] = True
        _save_user_data(user_data)
        _send(token, chat_id,
              "👋 <b>Welcome to Job CV Bot!</b>\n\n"
              "To get started, please send me your CV:\n"
              "• <b>Paste it</b> as plain text, or\n"
              "• <b>Upload</b> a <code>.pdf</code> or <code>.docx</code> file\n\n"
              "Once your CV is saved, send me any job URL and I'll generate "
              "a tailored CV + cover letter for you.")


def _store_cv(token: str, chat_id: int, user_data: dict, cv_text: str) -> None:
    """Validate and persist a CV string; sends confirmation."""
    if len(cv_text) < MIN_CV_LENGTH:
        _send(token, chat_id,
              f"❌ That looks too short to be a CV ({len(cv_text)} characters). "
              "Please paste your full CV text or upload a PDF/docx file.")
        user_data["awaiting_cv"] = True
        _save_user_data(user_data)
        return
    user_data["cv_text"] = cv_text
    user_data["awaiting_cv"] = False
    _save_user_data(user_data)
    _send(token, chat_id,
          "✅ CV saved! Now send me a job URL and I'll generate a tailored CV + cover letter.")


def _handle_document(token: str, chat_id: int, document: dict, user_data: dict) -> None:
    awaiting_cv = user_data.get("awaiting_cv", False)
    has_cv = bool(user_data.get("cv_text"))

    if not awaiting_cv and has_cv:
        _send(token, chat_id,
              "📄 To update your stored CV, use /updatecv first, then send the file.")
        return

    mime_type = document.get("mime_type", "")
    file_name = document.get("file_name", "")
    file_id = document.get("file_id", "")
    file_size = document.get("file_size", 0)

    if not file_id:
        _send(token, chat_id, "❌ Could not read the uploaded file.")
        return

    if file_size > MAX_FILE_SIZE:
        _send(token, chat_id,
              f"❌ File is too large ({file_size // 1024 // 1024}MB). "
              "Please upload a file under 5MB.")
        return

    _send(token, chat_id, "⏳ Processing your CV file...")

    try:
        file_bytes = _download_telegram_file(token, file_id)
    except Exception as e:
        _send(token, chat_id, f"❌ Could not download file:\n<code>{_he(str(e))}</code>")
        return

    try:
        if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
            cv_text = _extract_pdf_text(file_bytes)
        elif (mime_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ) or file_name.lower().endswith((".docx", ".doc"))):
            cv_text = _extract_docx_text(file_bytes)
        else:
            _send(token, chat_id,
                  "❌ Unsupported file type. Please upload a <code>.pdf</code> or "
                  "<code>.docx</code> file, or paste your CV as plain text.")
            return
    except RuntimeError as e:
        _send(token, chat_id, f"❌ {_he(str(e))}")
        return

    _store_cv(token, chat_id, user_data, cv_text)


# ── Job page scraping ─────────────────────────────────────────────────────────

def _extract_with_requests(url: str) -> tuple[str, str, str]:
    """Fast path: plain HTTP fetch + BeautifulSoup."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_soup(soup, url)


def _extract_with_playwright(url: str) -> tuple[str, str, str]:
    """Slow path: render JS-heavy pages with Playwright."""
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed in this environment.")
    with _playwright_sem:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
    soup = BeautifulSoup(html, "html.parser")
    return _parse_soup(soup, url)


def _render_pdf_safe(markdown: str, path: Path) -> Path:
    """Render PDF with the Playwright concurrency semaphore held."""
    with _playwright_sem:
        return render_pdf(markdown, path)


def _parse_soup(soup: BeautifulSoup, url: str) -> tuple[str, str, str]:
    """Extract (title, company, description) from a BeautifulSoup document."""
    # ── Title ──
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
    if not title:
        page_title = soup.find("title")
        title = page_title.get_text(strip=True) if page_title else ""
    title = re.split(r"\s*[|\-–—]\s*", title)[0].strip()

    # ── Company ──
    company = ""
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        company = og_site["content"].strip()
    if not company:
        hiring_org = soup.find(attrs={"itemprop": "hiringOrganization"})
        if hiring_org:
            company = hiring_org.get_text(strip=True)
    if not company:
        company = urlparse(url).netloc.replace("www.", "").split(".")[0].capitalize()

    # ── Description ──
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

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
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            description = main.get_text(separator="\n", strip=True)

    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    description = "\n".join(lines[:300])

    return title or "Unknown Title", company or "Unknown Company", description or "No description found."


def fetch_job_page(url: str) -> tuple[str, str, str]:
    """Return (title, company, description) for a job URL.

    Tries fast HTTP first; falls back to Playwright if available.
    """
    _validate_url(url)  # SSRF guard — raises ValueError for private/internal targets
    try:
        return _extract_with_requests(url)
    except Exception as e:
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                f"Could not fetch this page with plain HTTP ({e}). "
                "The page likely requires JavaScript to load. "
                "Try copying the job description text and sending it as:\n\n"
                "<code>title: Software Engineer Intern\n"
                "company: Acme Corp\n"
                "---\n"
                "[paste description here]</code>"
            )
        logger.info("Fast HTTP failed (%s), retrying with Playwright", e)
    return _extract_with_playwright(url)


# ── CV generation ─────────────────────────────────────────────────────────────

def _safe_name(first_name: str) -> str:
    """Sanitize a Telegram first_name for use in filenames."""
    return re.sub(r"[^A-Za-z0-9]+", "", first_name)[:20] or "User"


def generate_and_send_cv(
    token: str, chat_id: int, url: str, user_data: dict, first_name: str
) -> None:
    user_cv = user_data["cv_text"]
    name_slug = _safe_name(first_name)

    _send(token, chat_id, "⏳ Fetching job page...")

    try:
        title, company, description = fetch_job_page(url)
    except Exception as e:
        _send(token, chat_id, f"❌ Could not fetch the job page:\n<code>{_he(str(e))}</code>")
        return

    _send(
        token, chat_id,
        f"📋 <b>{_he(title)}</b>\n"
        f"🏢 {_he(company)}\n\n"
        f"⚙️ Generating tailored CV + cover letter..."
    )

    try:
        cv_md = generate_tailored_cv(title, company, description, user_cv)
        cl_md = generate_cover_letter(title, company, description, user_cv)
    except Exception as e:
        _send(token, chat_id, f"❌ CV generation failed:\n<code>{_he(str(e))}</code>")
        return

    safe_title = re.sub(r"[^A-Za-z0-9]+", "", title)[:40]
    safe_company = re.sub(r"[^A-Za-z0-9]+", "", company)[:30]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            cv_path = _render_pdf_safe(cv_md, tmp / f"{name_slug}_CV_{safe_company}_{safe_title}.pdf")
            cl_path = _render_pdf_safe(cl_md, tmp / f"{name_slug}_CoverLetter_{safe_company}_{safe_title}.pdf")
        except Exception as e:
            _send(token, chat_id, f"❌ PDF rendering failed:\n<code>{_he(str(e))}</code>")
            return

        _send(token, chat_id, "✅ Done! Sending PDFs...")
        _send_pdf(token, chat_id, cv_path)
        _send_pdf(token, chat_id, cl_path)

    logger.info("Sent CV + cover letter for '%s' at '%s' to chat %s",
                _safe_log(title), _safe_log(company), chat_id)


def _handle_manual_text(
    token: str, chat_id: int, text: str, user_data: dict, first_name: str
) -> None:
    """Parse manual format and generate CV without fetching any URL.

    Expected format:
        title: Software Engineer Intern
        company: Acme Corp
        ---
        <full job description>
    """
    user_cv = user_data["cv_text"]
    name_slug = _safe_name(first_name)

    try:
        header, _, description = text.partition("---")
        title, company = "", ""
        for line in header.splitlines():
            if line.lower().startswith("title:"):
                title = line.split(":", 1)[1].strip()
            elif line.lower().startswith("company:"):
                company = line.split(":", 1)[1].strip()
        description = description.strip()
        if not title or not company or not description:
            _send(token, chat_id,
                  "❌ Could not parse the text. Use this format:\n\n"
                  "<code>title: Job Title\ncompany: Company Name\n---\nDescription here</code>")
            return
    except Exception as e:
        _send(token, chat_id, f"❌ Parse error: {_he(str(e))}")
        return

    _send(token, chat_id,
          f"📋 <b>{_he(title)}</b> at {_he(company)}\n⚙️ Generating CV...")

    try:
        cv_md = generate_tailored_cv(title, company, description, user_cv)
        cl_md = generate_cover_letter(title, company, description, user_cv)
    except Exception as e:
        _send(token, chat_id, f"❌ CV generation failed: {_he(str(e))}")
        return

    safe_title = re.sub(r"[^A-Za-z0-9]+", "", title)[:40]
    safe_company = re.sub(r"[^A-Za-z0-9]+", "", company)[:30]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            cv_path = _render_pdf_safe(cv_md, tmp / f"{name_slug}_CV_{safe_company}_{safe_title}.pdf")
            cl_path = _render_pdf_safe(cl_md, tmp / f"{name_slug}_CoverLetter_{safe_company}_{safe_title}.pdf")
        except Exception as e:
            _send(token, chat_id, f"❌ PDF rendering failed: {_he(str(e))}")
            return

        _send(token, chat_id, "✅ Done! Sending PDFs...")
        _send_pdf(token, chat_id, cv_path)
        _send_pdf(token, chat_id, cl_path)

    logger.info("Sent CV (manual text) for '%s' at '%s' to chat %s",
                _safe_log(title), _safe_log(company), chat_id)


# ── Bot loop ──────────────────────────────────────────────────────────────────

_PLAYWRIGHT_NOTE = (
    "" if _PLAYWRIGHT_AVAILABLE else
    "\n\n⚠️ <b>JS-rendered pages:</b> If a URL fails, paste the job manually:\n"
    "<code>title: Software Engineer Intern\ncompany: Acme Corp\n---\n[description here]</code>"
)

HELP_TEXT = (
    "👋 <b>Job CV Bot</b>\n\n"
    "Send me your CV first (paste as text or upload PDF/docx), then send job URLs.\n\n"
    "<b>Commands:</b>\n"
    "/start — show this welcome message\n"
    "/updatecv — replace your stored CV\n"
    "/deletecv — permanently delete your stored CV and data\n\n"
    "<b>Option 1 — URL:</b>\n"
    "<code>https://jobs.nvidia.com/jobs/XXXXX</code>\n\n"
    "<b>Option 2 — Manual text</b> (if URL fails):\n"
    "<code>title: Software Engineer Intern\n"
    "company: Acme Corp\n"
    "---\n"
    "[paste full job description here]</code>"
    + _PLAYWRIGHT_NOTE
)


def _process_update(token: str, update: dict) -> None:
    """Handle a single Telegram update. Runs inside a worker thread."""
    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return

    first_name = msg.get("from", {}).get("first_name", "User")
    text = (msg.get("text") or "").strip()
    document = msg.get("document")

    if not text and not document:
        return

    try:
        user_data = _load_user_data(chat_id)

        # ── Commands ──────────────────────────────────────────────────────
        if text in ("/start", "/help"):
            _handle_start(token, chat_id, user_data)
            return

        if text == "/updatecv":
            user_data["awaiting_cv"] = True
            _save_user_data(user_data)
            _send(token, chat_id,
                  "📄 Send your new CV — paste the full text or upload a PDF/docx file.")
            return

        if text == "/deletecv":
            path = USER_DATA_DIR / f"{chat_id}.json"
            with _get_user_lock(chat_id):
                if path.exists():
                    path.unlink()
                    deleted = True
                else:
                    deleted = False
            if deleted:
                _send(token, chat_id,
                      "🗑️ Your CV and all stored data have been permanently deleted.")
            else:
                _send(token, chat_id, "No stored data found for your account.")
            return

        # ── Document upload ───────────────────────────────────────────────
        if document:
            _handle_document(token, chat_id, document, user_data)
            return

        # ── Text messages ─────────────────────────────────────────────────
        awaiting_cv = user_data.get("awaiting_cv", False)
        has_cv = bool(user_data.get("cv_text"))

        # URL handling
        urls = URL_RE.findall(text)
        if urls:
            if not has_cv:
                _send(token, chat_id,
                      "📄 Please send your CV first (paste text or upload a PDF/docx file), "
                      "then I can process job URLs for you.")
                user_data["awaiting_cv"] = True
                _save_user_data(user_data)
                return
            if not _check_rate_limit(chat_id):
                _send(token, chat_id,
                      f"⏳ Slow down — max {_RATE_MAX} requests per minute. Try again shortly.")
                return
            generate_and_send_cv(token, chat_id, urls[0], user_data, first_name)
            return

        # Manual job format
        if text.lower().startswith("title:") and "---" in text:
            if not has_cv:
                _send(token, chat_id,
                      "📄 Please send your CV first before processing job descriptions.")
                user_data["awaiting_cv"] = True
                _save_user_data(user_data)
                return
            if not _check_rate_limit(chat_id):
                _send(token, chat_id,
                      f"⏳ Slow down — max {_RATE_MAX} requests per minute. Try again shortly.")
                return
            _handle_manual_text(token, chat_id, text, user_data, first_name)
            return

        # Plain text — CV upload path
        if awaiting_cv or not has_cv:
            _store_cv(token, chat_id, user_data, text)
            return

        # User has CV but sent unrecognised plain text
        _send(token, chat_id,
              "📎 Send a job URL, or type /help to see all options.")

    except Exception:
        logger.exception("Unhandled error processing update for chat %s", chat_id)
        try:
            _send(token, chat_id, "❌ An unexpected error occurred. Please try again.")
        except Exception:
            pass


def run(token: str) -> None:
    offset = 0
    logger.info("Bot started — %d worker threads, max %d Playwright instances",
                MAX_WORKERS, MAX_PLAYWRIGHT_INSTANCES)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="bot-worker") as pool:
        while True:
            try:
                result = _api(token, "getUpdates", data={
                    "offset": offset,
                    "timeout": 30,
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
                # Advance offset immediately in the poll thread — never in a worker —
                # so a worker crash doesn't cause the same update to be reprocessed.
                offset = update["update_id"] + 1
                pool.submit(_process_update, token, update)


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
