from dataclasses import dataclass, field, asdict
import json
from pathlib import Path


@dataclass
class EpisodeResult:
    id: str
    title: str
    show_name: str
    description: str
    release_date: str
    duration_ms: int
    spotify_url: str
    show_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ScoredEpisode:
    episode: EpisodeResult
    relevance_score: int  # 0-100

    def to_dict(self) -> dict:
        d = self.episode.to_dict()
        d["relevance_score"] = self.relevance_score
        return d


@dataclass
class Utterance:
    speaker: int
    text: str
    start: float
    end: float


@dataclass
class Transcript:
    utterances: list[Utterance]
    raw_text: str

    def to_dict(self) -> dict:
        return {
            "utterances": [
                {"speaker": u.speaker, "text": u.text, "start": u.start, "end": u.end}
                for u in self.utterances
            ],
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        utterances = [Utterance(**u) for u in d["utterances"]]
        return cls(utterances=utterances, raw_text=d["raw_text"])

    def formatted(self, max_utterances: int | None = None) -> str:
        utts = self.utterances[:max_utterances] if max_utterances else self.utterances
        lines = []
        for u in utts:
            lines.append(f"[Speaker {u.speaker}] {u.text}")
        return "\n".join(lines)


@dataclass
class TranscriptInsights:
    """Structured analysis of a podcast transcript, extracted before drafting."""
    person_name: str
    quotes: list[str]  # 3-5 verbatim quotes that reveal personality/opinions
    topics: list[str]  # Key topics they spoke about with conviction
    personality_signals: list[str]  # How they communicate (humor, directness, etc.)
    hooks: list[str]  # Specific things they said that create natural email openers
    pain_points: list[str]  # Problems/frustrations they mentioned
    goals: list[str]  # What they're working toward or excited about

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptInsights":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def formatted(self) -> str:
        sections = []
        if self.quotes:
            sections.append("VERBATIM QUOTES:\n" + "\n".join(f'- "{q}"' for q in self.quotes))
        if self.topics:
            sections.append("KEY TOPICS:\n" + "\n".join(f"- {t}" for t in self.topics))
        if self.personality_signals:
            sections.append("PERSONALITY:\n" + "\n".join(f"- {p}" for p in self.personality_signals))
        if self.hooks:
            sections.append("HOOKS (natural openers):\n" + "\n".join(f"- {h}" for h in self.hooks))
        if self.pain_points:
            sections.append("PAIN POINTS:\n" + "\n".join(f"- {p}" for p in self.pain_points))
        if self.goals:
            sections.append("GOALS:\n" + "\n".join(f"- {g}" for g in self.goals))
        return "\n\n".join(sections)


@dataclass
class DraftedEmail:
    subject: str
    body: str
    template_type: str
