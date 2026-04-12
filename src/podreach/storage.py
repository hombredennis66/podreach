import json
import re
from pathlib import Path

from podreach.models import EpisodeResult, ScoredEpisode, Transcript


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].rstrip("-")


def get_episode_dir(base_dir: str, person_name: str, episode: EpisodeResult) -> Path:
    person_slug = slugify(person_name)
    episode_slug = slugify(f"{episode.show_name}-{episode.title}-{episode.release_date}")
    return Path(base_dir) / person_slug / episode_slug


def save_episode_metadata(episode_dir: Path, episode: EpisodeResult, relevance_score: int = 0, person_query: str = "") -> None:
    episode_dir.mkdir(parents=True, exist_ok=True)
    data = episode.to_dict()
    data["relevance_score"] = relevance_score
    data["person_query"] = person_query
    (episode_dir / "episode.json").write_text(json.dumps(data, indent=2))


def load_episode_metadata(episode_dir: Path) -> dict:
    return json.loads((episode_dir / "episode.json").read_text())


def has_transcript(episode_dir: Path) -> bool:
    return (episode_dir / "transcript.json").exists()


def save_transcript(episode_dir: Path, transcript: Transcript) -> None:
    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "transcript.json").write_text(json.dumps(transcript.to_dict(), indent=2))


def load_transcript(episode_dir: Path) -> Transcript:
    data = json.loads((episode_dir / "transcript.json").read_text())
    return Transcript.from_dict(data)


def find_audio_files(episode_dir: Path) -> list[Path]:
    extensions = {".mp3", ".ogg", ".flac", ".wav", ".opus", ".m4a"}
    return [f for f in episode_dir.iterdir() if f.suffix.lower() in extensions]


def cleanup_audio(episode_dir: Path) -> list[Path]:
    deleted = []
    for f in find_audio_files(episode_dir):
        f.unlink()
        deleted.append(f)
    return deleted
