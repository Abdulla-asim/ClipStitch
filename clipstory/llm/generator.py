"""
LLM generator for ClipStory.
Orchestrates: fetch clips → build prompt → call provider → save output.
"""

import logging
from clipstory.db import store
from clipstory.llm.provider import get_provider
from clipstory.llm.prompts import MODES

log = logging.getLogger(__name__)


def generate(
    session_id: int,
    mode: str,
    clip_ids: list[int] | None = None,
) -> str:
    """
    Generate LLM output for a session.

    Args:
        session_id: The session to generate for.
        mode:       One of 'story', 'summary', 'worklog', 'digest', 'email', 'report'.
        clip_ids:   Optional list of specific clip IDs to use.
                    If None, all clips in the session are used.

    Returns:
        The generated text string.

    Raises:
        ValueError: If mode is unknown or session not found.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r}. Valid modes: {list(MODES)}")

    session = store.get_session(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found.")

    # Fetch clips
    if clip_ids:
        clips = store.get_clips_by_ids(clip_ids)
    else:
        clips = store.get_clips_for_session(session_id)
        clip_ids = [c["id"] for c in clips]

    if not clips:
        raise ValueError("No clips found for generation.")

    log.info("Generating mode=%r for session %d using %d clips", mode, session_id, len(clips))

    # Build prompt and call provider
    template_fn = MODES[mode]
    system_prompt, user_prompt = template_fn(session, clips)
    provider = get_provider()
    result = provider.complete(system_prompt, user_prompt)

    # Persist the output
    store.save_output(session_id, mode, result, clip_ids)
    log.info("Generation complete (%d chars)", len(result))

    return result
