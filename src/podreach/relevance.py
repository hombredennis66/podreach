import json

import anthropic

from podreach.models import EpisodeResult, ScoredEpisode


SCORING_SYSTEM_PROMPT = """You score podcast episodes for how likely a specific person ACTUALLY APPEARS on the episode (as a guest, host, or interviewee) versus merely being MENTIONED or DISCUSSED.

Score 0-100:
- 90-100: Strong evidence they appear (their name in title with "interview", "with", "featuring", "joins", or they are the host)
- 60-89: Likely appears (name in title, episode seems like a conversation with them)
- 30-59: Uncertain (name in description but not title, could be either)
- 0-29: Probably just mentioned (episode discusses them or their work without them present)

Respond with a JSON array of objects, one per episode, in the same order as input:
[{"index": 0, "score": 95, "reason": "Name in title with 'interview'"}, ...]

Be concise in reasons. Only output the JSON array, nothing else."""


def score_episodes(api_key: str, person_query: str, episodes: list[EpisodeResult]) -> list[ScoredEpisode]:
    if not episodes:
        return []

    episodes_text = "\n".join(
        f"[{i}] Title: {ep.title}\n    Show: {ep.show_name}\n    Description: {ep.description[:300]}"
        for i, ep in enumerate(episodes)
    )

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=SCORING_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Person searched: \"{person_query}\"\n\nEpisodes:\n{episodes_text}",
        }],
    )

    scores_text = resp.content[0].text.strip()
    # Strip markdown code fences if present
    if scores_text.startswith("```"):
        scores_text = scores_text.split("\n", 1)[1]
        if scores_text.endswith("```"):
            scores_text = scores_text.rsplit("```", 1)[0]

    try:
        scores = json.loads(scores_text)
    except json.JSONDecodeError:
        # Fallback: give all episodes 50%
        return [ScoredEpisode(episode=ep, relevance_score=50) for ep in episodes]

    scored = []
    score_map = {s["index"]: s["score"] for s in scores}
    for i, ep in enumerate(episodes):
        scored.append(ScoredEpisode(
            episode=ep,
            relevance_score=score_map.get(i, 50),
        ))

    scored.sort(key=lambda s: s.relevance_score, reverse=True)
    return scored
