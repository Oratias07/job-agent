"""CV Tailor sub-agent — uses Groq LLM to produce a tailored CV and cover letter."""

import os
import logging
from groq import Groq

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_CV = """You are a professional CV and cover letter writer specializing in tech internships and student roles.
You write for a recruiter who reviews 200+ CVs — your goal is to make this candidate visually and substantively stand out in the first 10 seconds of scanning.
Rules:
- Never fabricate experience, skills, or credentials
- Reorder and emphasize existing content to maximize relevance
- Use strong, specific action verbs
- Mirror terminology from the job description naturally
- Output clean Markdown only, no commentary, no preamble"""

SYSTEM_PROMPT_COVER = """You are a professional cover letter writer specializing in tech internships and student roles.
Rules:
- Tone: confident, direct, technical — not generic or overly formal
- Never fabricate experience, skills, or credentials
- Reference specific details from the job description
- Max 350 words
- Output clean Markdown only, no commentary, no preamble"""

BASE_CV = r"""# OR ATIAS
**Software Engineering Student | Systems Programming | Low-Level & AI-Integrated Development**
Braude College, Israel | [github.com/Oratias07](https://github.com/Oratias07) | [linkedin.com/in/oratias07](https://linkedin.com/in/oratias07) | AI workflow: [github.com/Oratias07/AI-workflow](https://github.com/Oratias07/AI-workflow)

## PROFESSIONAL SUMMARY
Second-year Software Engineering student (85 GPA) with hands-on experience spanning low-level C/C++, AI-integrated web applications, and x86 Assembly. Concurrently teaches programming at the Ministry of Defense and supports systems coursework at Braude College — translating technical depth into clear, practical instruction. Methodical and self-driven; motivated to contribute to Post-Silicon validation, performance engineering, and software automation.

## TECHNICAL SKILLS
- **Languages:** C, C++, Python, TypeScript, Assembly (x86)
- **Domains:** Systems Programming, Memory Architecture, Post-Silicon Logic, Algorithms, AI Integration
- **Tools & Env:** Git, GitHub, VSCode, JetBrains, Spyder
- **Core Strengths:** Analytical reasoning, rapid self-learning, attention to detail, clear technical communication

## EXPERIENCE

### Programming Instructor — C Language | Cyber Education Program, Ministry of Defense | 2025–Present
- Design and deliver a structured C curriculum for beginners: pointers, memory layout, arrays, recursion, and problem decomposition — building systematic thinking from the ground up
- Develop original course materials and exercises tailored to accelerate understanding under time-constrained conditions
- Guide learners through fault isolation and structured error analysis, with measurable gains in independent problem-solving

### Systems Programming Facilitator | Braude College of Engineering | 2025–Present
- Support advanced coursework in file I/O, dynamic allocation, ADTs, and pointer manipulation through one-on-one code review and logic walkthroughs
- Recognized by faculty for clear, precise explanations of runtime behavior and segmentation-fault diagnostics

### Software Coordinator — Student Association | Braude College of Engineering | 2024–Present
- Act as technical liaison between students and administration, resolving software issues and streamlining institutional workflows
- Coordinate cross-departmental communication to reduce response time on technology-related requests

## PROJECTS

### ST-System — AI-Powered Grading Platform | TypeScript | Live Deployment | 2025
- Architected and shipped a full-stack web application that automates assignment evaluation using an AI engine, generating consistent, criteria-based scores at scale
- Built with academic integrity compliance in mind; features a structured grading pipeline and clean UI
- GitHub: [github.com/Oratias07/ST-System](https://github.com/Oratias07/ST-System)

### Academic Research Report on AI-based automatic code assessment (CHAM model) | 2026
- Focused on LLM-based code grading for a Hebrew educational SaaS platform
- Identified key architectural/pedagogical risks and proposed a three-layer hybrid human-in-the-loop assessment model

### Learning Center by Gemini — Conversational Study Tool | TypeScript | 2025
- Developed an AI-powered chat interface via the Gemini API that delivers on-demand concept explanations and reinforcement
- GitHub: [github.com/Oratias07/Learning-Center-by-Gemini](https://github.com/Oratias07/Learning-Center-by-Gemini)

### Custom Dynamic Memory Allocator & Pointer-Chain | C | 2024–2025
- Built a malloc/free analogue from scratch using raw pointer arithmetic and manual metadata tracking, with zero reliance on standard library abstractions
- Stress-tested against boundary overflows, double-free, and fragmentation edge cases; extended into a reference debugging utility for systems coursework
- GitHub: [github.com/Oratias07/C-protfolio](https://github.com/Oratias07/C-protfolio)

### Computing Fundamentals — x86 Assembly | 2025
- Implemented low-level programs exercising CPU instruction sets and register management, deepening understanding of the hardware-software boundary

## EDUCATION
**B.Sc. Software Engineering** | Braude College of Engineering | 2024–2028 (Expected)
- GPA: 85 average (Semester 4, ~2 years completed)
- Relevant Coursework: Data Structures & Algorithms (85), Systems Programming, Computer Architecture, ADTs
- Languages: Hebrew (native), English (advanced)
"""


def _call_groq(system_prompt: str, user_prompt: str) -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2000,
        temperature=0.3,
    )
    return response.choices[0].message.content


def generate_tailored_cv(job_title: str, company: str, description: str) -> str:
    """Return tailored CV as Markdown."""
    user_prompt = f"""Below is the base CV and the target job description.
Produce a tailored CV that reorders and reweights the base content to maximize relevance for this specific role.
- Promote the most relevant experience/projects to top positions
- Expand bullet points that directly match keywords in the job description
- Trim or compress less relevant sections
- Adjust the Professional Summary to speak directly to this role
- Do NOT fabricate anything — only reorganize, expand, or compress existing content

## Target Job
**{job_title}** at **{company}**

### Job Description
{description}

## Base CV
{BASE_CV}
"""
    result = _call_groq(SYSTEM_PROMPT_CV, user_prompt)
    logger.info("Generated tailored CV for %s at %s", job_title, company)
    return result


def generate_cover_letter(job_title: str, company: str, description: str) -> str:
    """Return cover letter as Markdown."""
    user_prompt = f"""Write a cover letter for the following job, based on the candidate's CV below.
Structure:
- Opening: why this specific company and role (use actual details from the job description)
- Middle: 2–3 specific points connecting the candidate's background to the job requirements
- Closing: clear call to action
Max 350 words. Confident, direct, technical tone.

## Target Job
**{job_title}** at **{company}**

### Job Description
{description}

## Candidate CV
{BASE_CV}
"""
    result = _call_groq(SYSTEM_PROMPT_COVER, user_prompt)
    logger.info("Generated cover letter for %s at %s", job_title, company)
    return result
