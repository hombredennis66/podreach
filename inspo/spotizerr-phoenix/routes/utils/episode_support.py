import time
from pathlib import Path


AUDIO_EXTENSIONS = {".mp3", ".ogg", ".flac", ".wav", ".opus", ".m4a"}


def extract_status_info(progress_data: dict | None) -> dict:
    if not isinstance(progress_data, dict):
        return {}
    status_info = progress_data.get("status_info")
    return status_info if isinstance(status_info, dict) else {}


def extract_track_object(progress_data: dict | None) -> dict:
    if not isinstance(progress_data, dict):
        return {}
    track = progress_data.get("track")
    return track if isinstance(track, dict) else {}


def extract_episode_identity(progress_data: dict | None) -> tuple[str, str]:
    track = extract_track_object(progress_data)
    album = track.get("album")
    album = album if isinstance(album, dict) else {}
    artists = track.get("artists")
    artists = artists if isinstance(artists, list) else []

    title = (
        track.get("title")
        or (progress_data or {}).get("song")
        or (progress_data or {}).get("name")
        or "Unknown"
    )
    show_name = (
        album.get("title")
        or next(
            (
                artist.get("name")
                for artist in artists
                if isinstance(artist, dict) and artist.get("name")
            ),
            "",
        )
        or (progress_data or {}).get("artist")
        or (progress_data or {}).get("show")
        or "Unknown"
    )
    return str(title), str(show_name)


def extract_final_path(progress_data: dict | None) -> str:
    candidates = []
    if isinstance(progress_data, dict):
        candidates.append(progress_data.get("final_path"))
        status_info = extract_status_info(progress_data)
        candidates.append(status_info.get("final_path"))

    for candidate in candidates:
        if candidate:
            return str(Path(candidate).expanduser())
    return ""


def extract_terminal_reason(progress_data: dict | None) -> str:
    if not isinstance(progress_data, dict):
        return ""

    status_info = extract_status_info(progress_data)
    for key in ("terminal_reason", "error", "message", "reason"):
        value = status_info.get(key)
        if value:
            return str(value)

    for key in ("terminal_reason", "error", "message", "reason"):
        value = progress_data.get(key)
        if value:
            return str(value)

    return ""


def normalize_episode_tags(tags: dict | None) -> dict:
    normalized = dict(tags or {})

    name = (
        normalized.get("name")
        or normalized.get("music")
        or normalized.get("title")
        or normalized.get("song")
    )
    show = (
        normalized.get("show")
        or normalized.get("album")
        or normalized.get("show_name")
        or normalized.get("podcast_name")
        or normalized.get("album_name")
    )
    artist = (
        normalized.get("artist")
        or normalized.get("ar_album")
        or normalized.get("publisher")
    )

    if name:
        name = str(name)
        normalized.setdefault("name", name)
        normalized.setdefault("title", name)
        normalized.setdefault("music", name)

    if show:
        show = str(show)
        normalized.setdefault("show", show)
        normalized.setdefault("show_name", show)
        normalized.setdefault("podcast_name", show)
        normalized.setdefault("album_name", show)
        normalized.setdefault("album", show)

    if artist:
        artist = str(artist)
        normalized.setdefault("artist", artist)
        normalized.setdefault("publisher", artist)
        normalized.setdefault("ar_album", artist)

    if name and show and not normalized.get("episode_name"):
        normalized["episode_name"] = f"{name} - {show}"

    return normalized


def update_episode_retry_state(
    task_info: dict,
    progress_data: dict,
    *,
    now: float | None = None,
    repeat_limit: int = 6,
    seconds_limit: int = 90,
) -> tuple[dict, str]:
    now = time.time() if now is None else now
    status_info = extract_status_info(progress_data)
    ids = status_info.get("ids")
    ids = ids if isinstance(ids, dict) else {}
    track = extract_track_object(progress_data)
    track_ids = track.get("ids")
    track_ids = track_ids if isinstance(track_ids, dict) else {}
    stable_id = ids.get("spotify") or track_ids.get("spotify") or task_info.get("url") or task_info.get("name", "")
    error = extract_terminal_reason(progress_data) or "Unknown error"
    signature = f"{stable_id}::{error}"

    previous = task_info.get("episode_retry_circuit")
    previous = previous if isinstance(previous, dict) else {}
    if previous.get("signature") == signature:
        repeat_count = int(previous.get("repeat_count", 0)) + 1
        first_timestamp = float(previous.get("first_timestamp", now))
    else:
        repeat_count = 1
        first_timestamp = now

    elapsed = max(0, int(now - first_timestamp))
    state = {
        "signature": signature,
        "repeat_count": repeat_count,
        "first_timestamp": first_timestamp,
        "last_timestamp": now,
        "last_error": error,
    }

    abort_reason = ""
    if repeat_count >= repeat_limit or elapsed >= seconds_limit:
        abort_reason = (
            f"Episode retry circuit opened after {repeat_count} identical retries "
            f"over {elapsed}s: {error}"
        )

    return state, abort_reason
