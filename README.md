# Job Agent

Automated job monitor that scrapes 7 job boards for student/intern positions in Israel, deduplicates cross-source listings, generates a tailored CV + cover letter per job via LLM, and delivers them via email and Telegram.

Also includes a **Telegram bot** (`bot_listener.py`) — send any job URL to the bot and receive a tailored PDF within ~30 seconds.

## How It Works

```mermaid
flowchart TD
    A["⏰ GitHub Actions Cron\n09:00 & 16:00 Israel Time"] --> B["🔍 Job Monitor Agent"]

    B --> C1["Microsoft R&D Israel\n(requests + BeautifulSoup)"]
    B --> C2["Microsoft Careers\n(Playwright)"]
    B --> C3["NVIDIA Careers\n(REST API / Playwright)"]
    B --> C4["Indeed Israel\n(RSS feed)"]
    B --> C5["AllJobs.co.il\n(Playwright)"]
    B --> C6["Drushim.co.il\n(Playwright)"]
    B --> C7["HiemeTech.com\n(Playwright)"]

    C1 & C2 & C3 & C4 & C5 & C6 & C7 --> D["🔎 Keyword Filter + Deduplication\nstudent · intern · סטודנט · התמחות"]

    D --> E{"New Jobs\nFound?"}

    E -- No --> F["✅ Done — nothing to do"]
    E -- "First Run" --> G["💾 Save Baseline\nNo notifications sent"]

    E -- Yes --> H["🤖 CV Tailor (Groq — Llama 3.3 70B)"]

    H --> H1["📄 Tailored CV (PDF)"]
    H --> H2["📄 Cover Letter (PDF)"]

    H1 & H2 --> I["📧 Gmail SMTP"]
    H1 & H2 --> J["📱 Telegram Bot"]

    I & J --> K["💾 Update seen_jobs.json\nCommit back to repo"]
```

## Project Structure

```
job-agent/
├── .github/workflows/
│   ├── job_check.yml          # Cron: runs twice daily
│   └── manual_job.yml         # Manual: paste a URL or job text → get PDFs
├── scraper/
│   ├── main.py                # Orchestrator: scrape → dedup → CV → notify
│   ├── notifier.py            # Email (Gmail SMTP) + Telegram
│   └── sites/
│       ├── microsoft_rnd.py   # Static HTML (requests + BS4)
│       ├── microsoft_careers.py # JS-rendered (Playwright)
│       ├── nvidia.py          # REST API with Playwright fallback
│       ├── indeed.py          # RSS feed (no browser)
│       ├── alljobs.py         # JS-rendered (Playwright)
│       ├── drushim.py         # JS-rendered (Playwright)
│       └── hiemetech.py       # JS-rendered (Playwright)
├── cv_agent/
│   ├── tailor.py              # Groq LLM — CV + cover letter generation
│   └── pdf_renderer.py        # Markdown → styled PDF (WeasyPrint)
├── bot_listener.py            # Telegram bot — URL → PDF on demand
├── tests/
│   ├── test_pdf_renderer.py   # HTML escaping, safe URLs, markdown conversion
│   ├── test_tailor.py         # Prompt injection defense, input sanitization
│   ├── test_main.py           # Deduplication, seen-jobs logic, main flow
│   ├── test_notifier.py       # Email/Telegram construction, escaping
│   ├── test_sites_indeed.py   # RSS parsing, keyword matching
│   ├── test_sites_microsoft_rnd.py  # HTML parsing, fallback scraper
│   └── test_bot_listener.py   # URL detection, HTML extraction, escaping
├── state/
│   └── seen_jobs.json         # Persistent job state (auto-committed by CI)
└── requirements.txt
```

## Setup

### 1. GitHub Secrets

Add in **Settings → Secrets and variables → Actions**:

| Secret | How to get it |
|--------|---------------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free tier |
| `GMAIL_APP_PASSWORD` | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — requires 2FA on the sender account |
| `TELEGRAM_BOT_TOKEN` | Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token |
| `TELEGRAM_CHAT_ID` | Send any message to your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat.id` number |

### 2. First Run (Baseline)

Go to **Actions → Job Monitor → Run workflow**. The first run saves all current jobs as a baseline — no CVs generated, no notifications sent. Only jobs that appear *after* the baseline trigger the pipeline.

### 3. Automatic Schedule

After the baseline, the agent runs at **09:00 and 16:00 Israel time** automatically.

---

## Telegram Bot (On-Demand CVs)

Run `bot_listener.py` on any machine (locally, Railway, Render, VPS):

```bash
export TELEGRAM_BOT_TOKEN=your_token
export GROQ_API_KEY=your_key
python bot_listener.py
```

Then send any job posting URL to your bot in Telegram — you'll get a tailored CV + cover letter PDF back within ~30 seconds. No description copying needed; the bot scrapes the page automatically (falls back to Playwright for JS-heavy sites).

---

## Manual Submission (GitHub Actions)

Found a job yourself? Use **Actions → Manual Job — Generate CV from URL or Text → Run workflow**:

- **Easiest:** paste just the `Job posting URL` — title and description are scraped automatically
- **Fallback:** fill in title + company + description manually

PDFs are sent to your email and Telegram.

---

## Security

- **Prompt injection defense:** job descriptions from scraped sources are wrapped in `<job_data>` XML delimiters and the system prompt explicitly instructs the LLM to treat content inside as raw data, not instructions
- **Input sanitization:** control characters and null bytes stripped; description truncated to 4000 chars
- **HTML injection:** all LLM output is HTML-escaped before rendering to PDF; link URLs validated against an allowlist (`https://`, `http://`, `mailto:`)
- **URL safety:** `javascript:` and `data:` URIs are blocked in generated PDFs

---

## Deduplication

The same job often appears on multiple boards (e.g. Microsoft R&D Israel + Microsoft Careers). After scraping, all results are deduplicated by normalized `(title, company-brand)` key. Among duplicates, the entry with the richest description is kept for CV generation. Company aliases are resolved (e.g. "Microsoft R&D Israel", "Microsoft Careers", "Microsoft" → `microsoft`).

---

## Job State & Retry Logic

State is stored in `state/seen_jobs.json` and committed back to the repo by CI after each run.

| State | Behaviour |
|-------|-----------|
| Never seen | Included as new — CV generated |
| First-run baseline (`baseline: true`) | Skipped forever |
| CV sent successfully (`sent_at: <timestamp>`) | Skipped |
| Scraped but email failed (no flags) | **Retried** on next run |

---

## Running Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

151 unit tests, 2 integration skips (WeasyPrint PDF render — requires GTK system libs, runs in CI).

Test coverage:
- `test_pdf_renderer.py` — HTML escaping, safe URL validation, markdown-to-HTML conversion
- `test_tailor.py` — prompt injection containment, input sanitization, prompt structure
- `test_main.py` — deduplication, seen-jobs migration, baseline, retry logic, full pipeline mocked
- `test_notifier.py` — email body/subject/attachment, Telegram API calls, MarkdownV2 escaping
- `test_sites_indeed.py` — RSS parsing, keyword matching, network failure handling
- `test_sites_microsoft_rnd.py` — HTML card parsing, link fallback, stable IDs
- `test_bot_listener.py` — URL detection, HTML parsing from job pages, Playwright fallback

---

## Stack

| Layer | Tool |
|-------|------|
| Scheduling | GitHub Actions (free tier) |
| HTTP scraping | `requests` + `BeautifulSoup` |
| JS-rendered pages | `playwright` (headless Chromium) |
| RSS parsing | `xml.etree.ElementTree` (stdlib) |
| LLM | Groq API — Llama 3.3 70B |
| PDF rendering | WeasyPrint |
| Email | Gmail SMTP (App Password) |
| Telegram | Bot API (long-polling) |
| Tests | `pytest` + `pytest-mock` |
