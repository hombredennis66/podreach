import json
import logging

import anthropic

from podreach.models import Transcript, TranscriptInsights, DraftedEmail
from podreach.templates import TEMPLATES, ANALYSIS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def analyze_transcript(
    api_key: str,
    transcript: Transcript,
    person_name: str,
    episode_metadata: dict,
) -> TranscriptInsights:
    """Stage 1: Extract actionable insights from the transcript for email drafting."""
    formatted_transcript = transcript.formatted(max_utterances=150)

    episode_context = (
        f"Episode: {episode_metadata.get('title', 'Unknown')}\n"
        f"Podcast: {episode_metadata.get('show_name', 'Unknown')}\n"
        f"Description: {episode_metadata.get('description', '')[:500]}"
    )

    user_message = (
        f"Person's name: {person_name}\n\n"
        f"Episode info:\n{episode_context}\n\n"
        f"Transcript:\n{formatted_transcript}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text = resp.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse transcript analysis JSON, using fallback")
        data = {
            "quotes": [], "topics": [], "personality_signals": [],
            "hooks": [], "pain_points": [], "goals": [],
        }

    return TranscriptInsights(
        person_name=person_name,
        quotes=data.get("quotes", []),
        topics=data.get("topics", []),
        personality_signals=data.get("personality_signals", []),
        hooks=data.get("hooks", []),
        pain_points=data.get("pain_points", []),
        goals=data.get("goals", []),
    )


def draft_email(
    api_key: str,
    transcript: Transcript,
    episode_metadata: dict,
    person_name: str,
    template_type: str,
    sender_context: str = "",
) -> DraftedEmail:
    """Two-stage pipeline: analyze transcript, then draft email from insights."""
    if template_type not in TEMPLATES:
        available = ", ".join(TEMPLATES.keys())
        raise ValueError(f"Unknown template '{template_type}'. Available: {available}")

    template = TEMPLATES[template_type]

    # Stage 1: Analyze transcript for insights
    insights = analyze_transcript(api_key, transcript, person_name, episode_metadata)
    logger.debug("Extracted insights: %s", insights.formatted())

    # Stage 2: Draft email from insights (not raw transcript)
    episode_context = (
        f"Episode: {episode_metadata.get('title', 'Unknown')}\n"
        f"Podcast: {episode_metadata.get('show_name', 'Unknown')}\n"
        f"Date: {episode_metadata.get('release_date', 'Unknown')}"
    )

    user_message = (
        f"Person's name: {person_name}\n\n"
        f"Episode info:\n{episode_context}\n\n"
        f"TRANSCRIPT ANALYSIS:\n{insights.formatted()}\n\n"
    )
    if sender_context:
        user_message += f"About me (the sender): {sender_context}\n\n"
    user_message += (
        "Write the outreach email. Format your response exactly as:\n"
        "SUBJECT: <subject line>\n"
        "BODY:\n<email body>"
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=template["system_prompt"],
        messages=[{"role": "user", "content": user_message}],
    )

    text = resp.content[0].text.strip()

    # Parse SUBJECT: and BODY: markers
    subject = ""
    body = text
    if "SUBJECT:" in text and "BODY:" in text:
        parts = text.split("BODY:", 1)
        subject_part = parts[0]
        body = parts[1].strip()
        if "SUBJECT:" in subject_part:
            subject = subject_part.split("SUBJECT:", 1)[1].strip()
    elif "SUBJECT:" in text:
        lines = text.split("\n", 1)
        subject = lines[0].replace("SUBJECT:", "").strip()
        body = lines[1].strip() if len(lines) > 1 else ""

    return DraftedEmail(subject=subject, body=body, template_type=template_type)
