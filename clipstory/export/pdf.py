"""
PDF report generation for ClipStory using ReportLab.

Structure:
  Page 1:  Cover — session date, duration, clip count
  Page 2:  LLM-generated content (story / summary / worklog etc.)
  Page 3+: Clip timeline — each clip in a styled block
  Footer:  Page number on every page
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
    KeepTogether,
)

from clipstory.db import store

# ─── Colour palette ───────────────────────────────────────────────────────────
INDIGO      = colors.HexColor("#6366f1")
SLATE_DARK  = colors.HexColor("#0f172a")
SLATE_MID   = colors.HexColor("#1e293b")
SLATE_LIGHT = colors.HexColor("#334155")
MUTED       = colors.HexColor("#94a3b8")
WHITE       = colors.white
ACCENT_URL  = colors.HexColor("#38bdf8")
ACCENT_CODE = colors.HexColor("#a78bfa")
ACCENT_TEXT = colors.HexColor("#34d399")

TYPE_COLORS = {
    "url":  ACCENT_URL,
    "code": ACCENT_CODE,
    "text": ACCENT_TEXT,
}

W, H = A4


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    def s(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    return {
        "cover_title": s("cover_title",
            fontSize=36, textColor=WHITE, fontName="Helvetica-Bold",
            alignment=TA_CENTER, spaceAfter=12),
        "cover_sub": s("cover_sub",
            fontSize=14, textColor=MUTED, fontName="Helvetica",
            alignment=TA_CENTER, spaceAfter=6),
        "cover_stat": s("cover_stat",
            fontSize=20, textColor=INDIGO, fontName="Helvetica-Bold",
            alignment=TA_CENTER, spaceAfter=4),
        "section_head": s("section_head",
            fontSize=18, textColor=INDIGO, fontName="Helvetica-Bold",
            spaceBefore=16, spaceAfter=8),
        "body": s("body",
            fontSize=10, textColor=colors.HexColor("#e2e8f0"),
            fontName="Helvetica", leading=16, spaceAfter=6),
        "clip_content": s("clip_content",
            fontSize=9, textColor=colors.HexColor("#cbd5e1"),
            fontName="Courier", leading=13, spaceAfter=4),
        "clip_meta": s("clip_meta",
            fontSize=8, textColor=MUTED, fontName="Helvetica",
            spaceAfter=2),
        "footer": s("footer",
            fontSize=8, textColor=MUTED, fontName="Helvetica",
            alignment=TA_CENTER),
    }


def _add_page_bg(canvas, doc):
    """Dark background on every page."""
    canvas.saveState()
    canvas.setFillColor(SLATE_DARK)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    # Accent bar at top
    canvas.setFillColor(INDIGO)
    canvas.rect(0, H - 0.4*cm, W, 0.4*cm, fill=1, stroke=0)
    # Footer text
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(W/2, 0.6*cm, f"ClipStory  ·  Page {doc.page}")
    canvas.restoreState()


def export_pdf(session_id: int, output_id: int | None = None) -> bytes:
    """
    Generate a PDF report and return the raw bytes.
    """
    session = store.get_session(session_id)
    clips   = store.get_clips_for_session(session_id)
    outputs = store.get_outputs_for_session(session_id)

    output = None
    if output_id:
        output = next((o for o in outputs if o["id"] == output_id), None)
    elif outputs:
        output = outputs[0]

    started  = datetime.fromisoformat(session["started_at"])
    ended    = datetime.fromisoformat(session["ended_at"]) if session.get("ended_at") else datetime.now()
    duration = int((ended - started).total_seconds() / 60)
    hours, mins = divmod(duration, 60)
    dur_str  = f"{hours}h {mins}m" if hours else f"{mins}m"

    styles = _build_styles()
    buf    = io.BytesIO()

    # Document with full-page frames
    frame = Frame(1.5*cm, 1.5*cm, W - 3*cm, H - 3*cm, id="main")
    tpl   = PageTemplate(id="main", frames=[frame], onPage=_add_page_bg)
    doc   = BaseDocTemplate(buf, pagesize=A4, pageTemplates=[tpl],
                            title="ClipStory Session Report",
                            author="ClipStory")

    story = []

    # ── Cover Page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("ClipStory", styles["cover_title"]))
    story.append(Paragraph("Session Report", styles["cover_sub"]))
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="80%", color=INDIGO, hAlign="CENTER"))
    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph(started.strftime("%B %d, %Y"), styles["cover_stat"]))
    story.append(Paragraph(started.strftime("%I:%M %p"), styles["cover_sub"]))
    story.append(Spacer(1, 0.6*cm))

    stat_data = [
        [Paragraph(f"<b>{len(clips)}</b>", styles["cover_stat"]),
         Paragraph(f"<b>{dur_str}</b>", styles["cover_stat"])],
        [Paragraph("Clips", styles["cover_sub"]),
         Paragraph("Duration", styles["cover_sub"])],
    ]
    stat_tbl = Table(stat_data, colWidths=[8*cm, 8*cm])
    stat_tbl.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER")]))
    story.append(stat_tbl)

    if session.get("label"):
        story.append(Spacer(1, 0.8*cm))
        story.append(Paragraph(session["label"], styles["cover_sub"]))

    story.append(PageBreak())

    # ── LLM Output ───────────────────────────────────────────────────────────
    if output:
        from clipstory.llm.prompts import MODE_LABELS
        label = MODE_LABELS.get(output["mode"], output["mode"].title())
        story.append(Paragraph(label, styles["section_head"]))
        story.append(HRFlowable(width="100%", color=SLATE_LIGHT))
        story.append(Spacer(1, 0.3*cm))

        for para in output["content"].split("\n\n"):
            para = para.strip()
            if not para:
                continue
            # Render markdown-style headings
            if para.startswith("## "):
                story.append(Spacer(1, 0.2*cm))
                story.append(Paragraph(para[3:], styles["section_head"]))
            elif para.startswith("### "):
                story.append(Paragraph(f"<b>{para[4:]}</b>", styles["body"]))
            else:
                safe = para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe, styles["body"]))

        story.append(PageBreak())

    # ── Clip Timeline ─────────────────────────────────────────────────────────
    story.append(Paragraph("Clip Timeline", styles["section_head"]))
    story.append(HRFlowable(width="100%", color=SLATE_LIGHT))
    story.append(Spacer(1, 0.3*cm))

    for i, c in enumerate(clips, 1):
        ts     = c["copied_at"][:16].replace("T", " ")
        ctype  = c["content_type"]
        color  = TYPE_COLORS.get(ctype, MUTED)
        lang   = f" · {c['language']}" if c.get("language") else ""
        title  = f" · {c['page_title']}" if c.get("page_title") else ""
        redact = " ⚠ REDACTED" if c.get("is_redacted") else ""

        meta = f"#{i}  {ts}  [{ctype.upper()}{lang}{title}]{redact}"
        content = c["content"].strip()
        if len(content) > 600:
            content = content[:600] + "…"
        safe_content = content.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

        block = KeepTogether([
            Paragraph(meta, styles["clip_meta"]),
            Paragraph(safe_content, styles["clip_content"]),
            HRFlowable(width="100%", color=SLATE_LIGHT, thickness=0.5),
            Spacer(1, 0.2*cm),
        ])
        story.append(block)

    doc.build(story)
    return buf.getvalue()
