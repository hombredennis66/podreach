import anthropic

from podreach.models import Transcript, DraftedEmail
from podreach.templates import TEMPLATES


def draft_email(
    api_key: str,
    transcript: Transcript,
    episode_metadata: dict,
    person_name: str,
    template_type: str,
    sender_context: str = "",
) -> DraftedEmail:
    if template_type not in TEMPLATES:
        available = ", ".join(TEMPLATES.keys())
        raise ValueError(f"Unknown template '{template_type}'. Available: {available}")

    template = TEMPLATES[template_type]
    formatted_transcript = transcript.formatted(max_utterances=100)

    episode_context = (
        f"Episode: {episode_metadata.get('title', 'Unknown')}\n"
        f"Podcast: {episode_metadata.get('show_name', 'Unknown')}\n"
        f"Description: {episode_metadata.get('description', '')[:500]}\n"
        f"Date: {episode_metadata.get('release_date', 'Unknown')}"
    )

    user_message = (
        f"Person's name: {person_name}\n\n"
        f"Episode info:\n{episode_context}\n\n"
        f"Podcast transcript:\n{formatted_transcript}\n\n"
    )
    if sender_context:
        user_message += f"Context about me (the sender): {sender_context}\n\n"
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
