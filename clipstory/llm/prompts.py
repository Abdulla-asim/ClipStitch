"""
Prompt templates for all ClipStory output modes.
Each template is a function that receives clip data and session metadata,
and returns (system_prompt, user_prompt) ready for the LLM.
"""

from datetime import datetime


def _format_clips(clips: list[dict]) -> str:
    """Format clips into a readable numbered list for the LLM."""
    lines = []
    for i, c in enumerate(clips, 1):
        ts = c.get("copied_at", "")[:16].replace("T", " ")
        ctype = c.get("content_type", "text").upper()
        lang  = f" [{c['language']}]" if c.get("language") else ""
        title = f' — "{c["page_title"]}"' if c.get("page_title") else ""
        content = c.get("content", "").strip()
        # Truncate very long clips in the prompt
        if len(content) > 800:
            content = content[:800] + "… [truncated]"
        lines.append(f"{i}. [{ts}] ({ctype}{lang}{title})\n   {content}")
    return "\n\n".join(lines)


def _meta(session: dict, clips: list[dict]) -> dict:
    """Compute session metadata for template substitution."""
    started = datetime.fromisoformat(session["started_at"])
    ended   = datetime.fromisoformat(session["ended_at"]) if session.get("ended_at") else datetime.now()
    duration_mins = int((ended - started).total_seconds() / 60)
    hours, mins = divmod(duration_mins, 60)
    dur_str = f"{hours}h {mins}m" if hours else f"{mins}m"
    return {
        "date":     started.strftime("%B %d, %Y"),
        "time":     started.strftime("%I:%M %p"),
        "duration": dur_str,
        "count":    len(clips),
        "clips":    _format_clips(clips),
    }


# ─── Mode: Narrative Story ────────────────────────────────────────────────────

def story(session: dict, clips: list[dict]) -> tuple[str, str]:
    m = _meta(session, clips)
    system = (
        "You are a creative writer. Your job is to weave a person's clipboard "
        "history into an engaging, coherent first-person narrative story. "
        "Make it flow naturally, infer context from the clips, and write as if "
        "describing a productive session to a friend. Keep it vivid and personal."
    )
    user = f"""Write a narrative story of this work session.

Session Date: {m['date']} starting at {m['time']}
Duration: {m['duration']}
Clips ({m['count']} total):

{m['clips']}

Write a flowing first-person story of what this person worked on during this session."""
    return system, user


# ─── Mode: Activity Summary ───────────────────────────────────────────────────

def summary(session: dict, clips: list[dict]) -> tuple[str, str]:
    m = _meta(session, clips)
    system = (
        "You are a productivity assistant. Analyse clipboard history and produce "
        "a concise, well-structured bullet-point summary of the key activities."
    )
    user = f"""Summarise this clipboard session into clear, actionable bullet points.

Session: {m['date']}, {m['duration']}
Clips ({m['count']} total):

{m['clips']}

Provide:
- A one-sentence overall summary
- 5–10 bullet points of key activities (group related items)
- Any notable tools, URLs, or technologies referenced"""
    return system, user


# ─── Mode: Work Log ───────────────────────────────────────────────────────────

def worklog(session: dict, clips: list[dict]) -> tuple[str, str]:
    m = _meta(session, clips)
    system = (
        "You are an assistant that helps engineers write professional work logs. "
        "Transform clipboard data into a chronological, timestamped work log "
        "suitable for standups, timesheets, or daily reports."
    )
    user = f"""Create a work log from this clipboard session.

Session: {m['date']}, {m['time']}, duration {m['duration']}
Clips ({m['count']} total):

{m['clips']}

Format as:
## Work Log — {m['date']}
**Total time:** {m['duration']}

### Timeline
[HH:MM] — Activity description
...

### Summary of Accomplishments
- ...

Keep entries concise and professional."""
    return system, user


# ─── Mode: Research Digest ────────────────────────────────────────────────────

def digest(session: dict, clips: list[dict]) -> tuple[str, str]:
    m = _meta(session, clips)
    system = (
        "You are a research analyst. Given a collection of notes, URLs, and text "
        "snippets from a research session, synthesise them into a structured digest "
        "with key findings, themes, and actionable next steps."
    )
    user = f"""Create a research digest from these clipboard items.

Session: {m['date']}, {m['duration']}
Items ({m['count']} total):

{m['clips']}

Produce:
## Research Digest — {m['date']}

### Theme / Topic
### Key Findings
- ...
### Sources Referenced
- ...
### Open Questions
- ...
### Next Steps
- ..."""
    return system, user


# ─── Mode: Email Draft ────────────────────────────────────────────────────────

def email(session: dict, clips: list[dict]) -> tuple[str, str]:
    m = _meta(session, clips)
    system = (
        "You are a professional writing assistant. Draft a concise, well-structured "
        "progress update email based on a person's clipboard activity. "
        "Tone: professional yet friendly."
    )
    user = f"""Draft a progress update email based on this work session.

Session: {m['date']}, {m['duration']}
Clips ({m['count']} total):

{m['clips']}

Format:
Subject: [meaningful subject line]

Hi [Team / Manager],

[Email body — 3–5 paragraphs summarising what was worked on, any blockers, and next steps]

Best regards,
[Name]"""
    return system, user


# ─── Mode: PDF Report ─────────────────────────────────────────────────────────

def report(session: dict, clips: list[dict]) -> tuple[str, str]:
    m = _meta(session, clips)
    system = (
        "You are a technical writer. Create a professionally structured session report "
        "with an executive summary, detailed activity breakdown, and conclusions. "
        "Use clear markdown headings. Be thorough and precise."
    )
    user = f"""Generate a detailed session report in markdown format.

Session: {m['date']}, {m['time']}, duration {m['duration']}
Clips ({m['count']} total):

{m['clips']}

Structure:
## Executive Summary
## Activity Breakdown
### [Topic/Task Group 1]
### [Topic/Task Group 2]
...
## Tools & Resources Used
## Key Outputs / Decisions
## Conclusions & Next Steps"""
    return system, user


# ─── Registry ─────────────────────────────────────────────────────────────────

MODES = {
    "story":   story,
    "summary": summary,
    "worklog": worklog,
    "digest":  digest,
    "email":   email,
    "report":  report,
}

MODE_LABELS = {
    "story":   "Narrative Story",
    "summary": "Activity Summary",
    "worklog": "Work Log",
    "digest":  "Research Digest",
    "email":   "Email Draft",
    "report":  "PDF Report",
}
