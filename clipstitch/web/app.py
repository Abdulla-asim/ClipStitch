"""
Flask web application for clipstitch.
Serves the dashboard UI and provides the REST API.
"""

import json
import logging
from datetime import datetime

from flask import Flask, jsonify, request, send_file, render_template, Response
import io

from clipstitch.db import store
from clipstitch.llm import generator
from clipstitch.llm.prompts import MODE_LABELS
from clipstitch.export import pdf as pdf_export
from clipstitch.export import markdown as md_export
from clipstitch import config as cfg

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_SORT_KEYS"] = False

# Reference to the running clipboard monitor (injected by main.py)
_monitor = None

def set_monitor(monitor):
    global _monitor
    _monitor = monitor


# ─── Status ──────────────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    sid = _monitor.current_session_id if _monitor else None
    clip_count = 0
    if sid:
        clip_count = len(store.get_clips_for_session(sid))
    return jsonify({
        "running": _monitor is not None and _monitor.is_alive(),
        "current_session_id": sid,
        "current_session_clips": clip_count,
        "provider": cfg.get("llm.provider"),
        "model": cfg.get("llm.model"),
    })


# ─── Sessions ────────────────────────────────────────────────────────────────

@app.get("/api/sessions")
def api_sessions():
    sessions = store.list_sessions()
    result = []
    for s in sessions:
        clips = store.get_clips_for_session(s["id"])
        started = datetime.fromisoformat(s["started_at"])
        ended   = datetime.fromisoformat(s["ended_at"]) if s.get("ended_at") else datetime.now()
        duration_mins = int((ended - started).total_seconds() / 60)
        result.append({
            **s,
            "clip_count": len(clips),
            "duration_mins": duration_mins,
            "is_active": s.get("ended_at") is None,
        })
    return jsonify(result)


@app.get("/api/sessions/<int:session_id>")
def api_session(session_id):
    s = store.get_session(session_id)
    if not s:
        return jsonify({"error": "Session not found"}), 404
    clips = store.get_clips_for_session(session_id)
    started = datetime.fromisoformat(s["started_at"])
    ended   = datetime.fromisoformat(s["ended_at"]) if s.get("ended_at") else datetime.now()
    duration_mins = int((ended - started).total_seconds() / 60)
    return jsonify({**s, "clip_count": len(clips), "duration_mins": duration_mins})


# ─── Clips ───────────────────────────────────────────────────────────────────

@app.get("/api/sessions/<int:session_id>/clips")
def api_clips(session_id):
    clips = store.get_clips_for_session(session_id)
    return jsonify(clips)


# ─── Generate ────────────────────────────────────────────────────────────────

@app.post("/api/sessions/<int:session_id>/generate")
def api_generate(session_id):
    body     = request.get_json(silent=True) or {}
    mode     = body.get("mode", "summary")
    clip_ids = body.get("clip_ids")  # optional list[int]

    try:
        text = generator.generate(session_id, mode, clip_ids)
        outputs = store.get_outputs_for_session(session_id)
        latest  = outputs[0] if outputs else {}
        return jsonify({
            "output_id": latest.get("id"),
            "mode": mode,
            "mode_label": MODE_LABELS.get(mode, mode),
            "content": text,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        log.exception("Generation error")
        return jsonify({"error": f"LLM error: {e}"}), 500


# ─── Outputs ─────────────────────────────────────────────────────────────────

@app.get("/api/sessions/<int:session_id>/outputs")
def api_outputs(session_id):
    outputs = store.get_outputs_for_session(session_id)
    # Enrich with mode label
    for o in outputs:
        o["mode_label"] = MODE_LABELS.get(o["mode"], o["mode"])
    return jsonify(outputs)


# ─── Export ──────────────────────────────────────────────────────────────────

@app.get("/api/sessions/<int:session_id>/export/pdf")
def api_export_pdf(session_id):
    output_id = request.args.get("output_id", type=int)
    try:
        data     = pdf_export.export_pdf(session_id, output_id)
        filename = md_export.filename_for_session(session_id, "pdf")
        return send_file(
            io.BytesIO(data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        log.exception("PDF export error")
        return jsonify({"error": str(e)}), 500


@app.get("/api/sessions/<int:session_id>/export/md")
def api_export_md(session_id):
    output_id = request.args.get("output_id", type=int)
    try:
        text     = md_export.export_markdown(session_id, output_id)
        filename = md_export.filename_for_session(session_id, "md")
        return Response(
            text,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        log.exception("Markdown export error")
        return jsonify({"error": str(e)}), 500


# ─── Settings ────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def api_settings_get():
    return jsonify(cfg.config)


@app.post("/api/settings")
def api_settings_post():
    body = request.get_json(silent=True) or {}
    try:
        # Deep-merge into config
        _deep_merge(cfg.config, body)
        cfg.save_config(cfg.config)
        # Reset LLM provider so it re-initialises with new settings
        from clipstitch.llm.provider import reset_provider
        reset_provider()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── SPA catch-all ───────────────────────────────────────────────────────────

@app.get("/")
@app.get("/<path:_>")
def index(_=""):
    return render_template("index.html")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, updates: dict) -> None:
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
