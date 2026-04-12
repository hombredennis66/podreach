import inspect
import logging
import os
import threading
import time
import traceback
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from deezspot.spotloader import SpoLogin

from routes.utils.credentials import (
    _get_global_spotify_api_creds,
    get_spotify_blob_path,
    get_spotify_device_info,
    device_info_summary,
)
from routes.utils.episode_support import (
    AUDIO_EXTENSIONS,
    extract_final_path,
    normalize_episode_tags,
)

logger = logging.getLogger(__name__)

_EPISODE_PATCH_APPLIED = False


def _snapshot_audio_files(directory: Path) -> dict[str, tuple[int, int]]:
    snapshot = {}
    if not directory.exists():
        return snapshot

    for file_path in directory.rglob("*"):
        if file_path.suffix.lower() not in AUDIO_EXTENSIONS or not file_path.is_file():
            continue
        stat = file_path.stat()
        snapshot[str(file_path.resolve())] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _pick_downloaded_episode_file(
    directory: Path,
    before_snapshot: dict[str, tuple[int, int]],
    started_at: float,
) -> Path:
    candidates = _find_recent_audio_candidates(directory, before_snapshot, started_at)

    if not candidates:
        raise FileNotFoundError("Episode download completed but no new audio file was produced.")

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _find_recent_audio_candidates(
    directory: Path,
    before_snapshot: dict[str, tuple[int, int]],
    started_at: float,
) -> list[Path]:
    candidates: list[Path] = []
    if not directory.exists():
        return candidates

    for file_path in directory.rglob("*"):
        if file_path.suffix.lower() not in AUDIO_EXTENSIONS or not file_path.is_file():
            continue

        stat = file_path.stat()
        resolved = str(file_path.resolve())
        marker = (stat.st_mtime_ns, stat.st_size)
        if before_snapshot.get(resolved) == marker and stat.st_mtime < started_at:
            continue
        if stat.st_mtime >= started_at or before_snapshot.get(resolved) != marker:
            candidates.append(file_path.resolve())

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates


def _get_spotify_episode_metadata(episode_id: str) -> dict:
    client_id, client_secret = _get_global_spotify_api_creds()
    if not client_id or not client_secret:
        raise ValueError("Global Spotify API credentials are required for episode metadata.")

    client = spotipy.Spotify(
        client_credentials_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
    )
    episode = client.episode(episode_id)
    show = episode.get("show") or {}
    return {
        "id": episode.get("id", episode_id),
        "name": episode.get("name", ""),
        "duration_ms": episode.get("duration_ms", 0),
        "explicit": episode.get("explicit", False),
        "images": episode.get("images", []),
        "available_markets": episode.get("languages", []),
        "show": {
            "id": show.get("id"),
            "name": show.get("name", ""),
            "publisher": show.get("publisher", ""),
        },
    }


def _extract_episode_id(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]


def _build_episode_track_payload(episode_id: str, metadata: dict | None) -> dict:
    metadata = metadata or {}
    show = metadata.get("show") if isinstance(metadata, dict) else {}
    show = show if isinstance(show, dict) else {}

    return {
        "type": "track",
        "title": metadata.get("name", f"Episode {episode_id}"),
        "ids": {"spotify": metadata.get("id", episode_id)},
        "album": {
            "type": "albumTrack",
            "album_type": "show",
            "title": show.get("name", "Podcast"),
            "ids": {"spotify": show.get("id")} if show.get("id") else {},
            "artists": [{"name": show.get("publisher", "")}],
        },
        "artists": [{"name": show.get("publisher", "")}],
    }


def apply_episode_runtime_patches() -> None:
    global _EPISODE_PATCH_APPLIED
    if _EPISODE_PATCH_APPLIED:
        return

    try:
        from librespot.core import ApiClient
        from librespot.mercury import RawMercuryRequest
        from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
        from librespot.proto import Metadata_pb2 as Metadata
        from librespot.audio import PlayableContentFeeder
        from librespot.structure import FeederException

        original_get_metadata_4_episode = ApiClient.get_metadata_4_episode
        original_load_episode = PlayableContentFeeder.load_episode

        def _patched_get_metadata_4_episode(self, episode):
            try:
                return original_get_metadata_4_episode(self, episode)
            except Exception as exc:
                session = getattr(self, "_ApiClient__session", None)
                if session is None:
                    raise

                response = session.mercury().send_sync(
                    RawMercuryRequest.get(episode.to_mercury_uri())
                )
                if not 200 <= response.status_code < 300 or not response.payload:
                    raise

                metadata = Metadata.Episode()
                metadata.ParseFromString(response.payload)
                logger.info(
                    "Fell back to Mercury episode metadata for %s after extended metadata failure: %s",
                    episode.to_spotify_uri(),
                    exc,
                )
                return metadata

        def _patched_load_episode(self, episode_id, audio_quality_picker, preload, halt_listener):
            picker = audio_quality_picker
            if not hasattr(picker, "get_file"):
                preferred_quality = (
                    picker
                    if isinstance(picker, AudioQuality)
                    else AudioQuality.NORMAL
                )
                picker = VorbisOnlyAudioQuality(preferred_quality)

            episode = self._PlayableContentFeeder__session.api().get_metadata_4_episode(episode_id)

            if getattr(episode, "audio", None):
                file = picker.get_file(episode.audio)
                if file is not None:
                    try:
                        return self.load_stream(file, None, episode, preload, halt_listener)
                    except Exception as exc:
                        logger.warning(
                            "Episode audio-file fallback failed for %s: %s",
                            episode_id.to_spotify_uri(),
                            exc,
                        )

            if getattr(episode, "external_url", ""):
                return original_load_episode(
                    self,
                    episode_id,
                    picker,
                    preload,
                    halt_listener,
                )

            raise FeederException("Cannot find suitable audio file")

        ApiClient.get_metadata_4_episode = _patched_get_metadata_4_episode
        PlayableContentFeeder.load_episode = _patched_load_episode
        logger.info("Applied owned episode metadata fallback patch for librespot ApiClient")
    except Exception as exc:
        logger.warning("Failed to patch librespot episode metadata fallback: %s", exc)

    try:
        from deezspot.easy_spoty import Spo

        def _patched_get_episode(cls, episode_id):
            return _get_spotify_episode_metadata(episode_id)

        Spo.get_episode = classmethod(_patched_get_episode)
        logger.info("Applied owned episode metadata patch for deezspot Spo.get_episode")
    except Exception as exc:
        logger.warning("Failed to patch deezspot episode metadata lookup: %s", exc)

    try:
        from deezspot.models.download.episode import Episode as DeezspotEpisode

        original_init = DeezspotEpisode.__init__
        original_getattr = getattr(DeezspotEpisode, "__getattr__", None)

        def _patched_init(self, tags, *args, **kwargs):
            normalized_tags = normalize_episode_tags(tags)
            return original_init(self, normalized_tags, *args, **kwargs)

        def _patched_getattr(self, attr_name):
            alias_map = {
                "name": ("music", "title", "episode_name"),
                "show": ("album", "show_name", "podcast_name", "album_name"),
            }
            for alias in alias_map.get(attr_name, ()):
                try:
                    value = object.__getattribute__(self, alias)
                except AttributeError:
                    continue
                if value not in (None, ""):
                    return value

            if callable(original_getattr):
                return original_getattr(self, attr_name)
            raise AttributeError(
                f"{type(self).__name__!s} object has no attribute {attr_name!r}"
            )

        DeezspotEpisode.__init__ = _patched_init
        DeezspotEpisode.__getattr__ = _patched_getattr
        logger.info("Applied owned episode model compatibility patch for deezspot Episode")
    except Exception as exc:
        logger.warning("Failed to patch deezspot Episode model compatibility: %s", exc)

    _EPISODE_PATCH_APPLIED = True


def _filter_supported_kwargs(func, kwargs: dict) -> dict:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return kwargs

    supported = {}
    for name, value in kwargs.items():
        if name in signature.parameters:
            supported[name] = value
    return supported


def download_episode(
    url,
    main,
    fallback=None,
    quality=None,
    fall_quality=None,
    real_time=False,
    custom_dir_format=None,
    custom_track_format=None,
    pad_tracks=True,
    save_cover=False,
    initial_retry_delay=5,
    retry_delay_increase=5,
    max_retries=3,
    progress_callback=None,
    convert_to=None,
    bitrate=None,
    artist_separator="; ",
    recursive_quality=False,
    spotify_metadata=True,
    _is_celery_task_execution=False,
    real_time_multiplier=None,
):
    stop_heartbeat = threading.Event()
    heartbeat_thread = None
    try:
        if not main:
            raise ValueError("Spotify account name is required for episode downloads.")

        if "open.spotify.com" not in url.lower():
            raise ValueError("Invalid URL: Must be from open.spotify.com")

        apply_episode_runtime_patches()

        global_spotify_client_id, global_spotify_client_secret = _get_global_spotify_api_creds()
        if not global_spotify_client_id or not global_spotify_client_secret:
            raise ValueError("Global Spotify API credentials are required for episode downloads.")

        blob_file_path = get_spotify_blob_path(main)
        if not os.path.exists(str(blob_file_path)):
            raise FileNotFoundError(
                f"Spotify credentials blob not found for account: {main}"
            )

        device_info = get_spotify_device_info(main)
        logger.info(
            "Using Spotify device info for account '%s' in episode download (%s)",
            main,
            device_info_summary(device_info),
        )

        if quality is None:
            quality = "HIGH"

        output_dir = Path("./downloads").resolve()
        before_snapshot = _snapshot_audio_files(output_dir)
        started_at = time.time()
        observed_final_path = {"value": ""}
        episode_id = _extract_episode_id(url)
        episode_metadata = _get_spotify_episode_metadata(episode_id)
        track_payload = _build_episode_track_payload(episode_id, episode_metadata)

        def _wrapped_progress_callback(progress_data):
            final_path = extract_final_path(progress_data)
            if final_path:
                observed_final_path["value"] = str(Path(final_path).resolve())
            if progress_callback:
                progress_callback(progress_data)

        def _heartbeat_loop():
            while not stop_heartbeat.wait(10):
                latest_candidates = _find_recent_audio_candidates(
                    output_dir,
                    before_snapshot,
                    started_at,
                )
                bytes_received = 0
                if latest_candidates:
                    try:
                        bytes_received = latest_candidates[0].stat().st_size
                    except FileNotFoundError:
                        bytes_received = 0

                _wrapped_progress_callback(
                    {
                        "track": track_payload,
                        "status_info": {
                            "status": "real_time",
                            "bytes_received": bytes_received,
                            "percentage": 0,
                        },
                        "timestamp": time.time(),
                    }
                )

        spo = None
        for attempt in range(5):
            try:
                spo = SpoLogin(
                    credentials_path=str(blob_file_path),
                    spotify_client_id=global_spotify_client_id,
                    spotify_client_secret=global_spotify_client_secret,
                    progress_callback=_wrapped_progress_callback,
                    device_info=device_info,
                )
                break
            except (ConnectionRefusedError, OSError) as exc:
                logger.warning("Episode session not ready (attempt %s/5): %s", attempt + 1, exc)
                if attempt == 4:
                    raise
                time.sleep(5)

        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"episode-heartbeat-{episode_id}",
            daemon=True,
        )
        heartbeat_thread.start()

        download_kwargs = {
            "link_episode": url,
            "output_dir": str(output_dir),
            "quality_download": quality,
            "recursive_quality": recursive_quality,
            "recursive_download": False,
            "not_interface": False,
            "real_time_dl": True,
            "custom_dir_format": custom_dir_format,
            "custom_track_format": custom_track_format,
            "pad_tracks": pad_tracks,
            "save_cover": save_cover,
            "initial_retry_delay": initial_retry_delay,
            "retry_delay_increase": retry_delay_increase,
            "max_retries": max_retries,
            "convert_to": convert_to,
            "bitrate": bitrate,
            "artist_separator": artist_separator,
            "real_time_multiplier": real_time_multiplier if real_time_multiplier is not None else 0,
        }
        supported_kwargs = _filter_supported_kwargs(spo.download_episode, download_kwargs)
        supported_kwargs["progress_callback"] = _wrapped_progress_callback
        supported_kwargs = _filter_supported_kwargs(spo.download_episode, supported_kwargs)

        logger.info("Downloading episode from: %s", url)
        spo.download_episode(**supported_kwargs)

        if observed_final_path["value"]:
            final_path = Path(observed_final_path["value"])
            if final_path.exists():
                logger.info("Episode download completed at exact path: %s", final_path)
                return final_path

        final_path = _pick_downloaded_episode_file(output_dir, before_snapshot, started_at)
        logger.info("Episode download completed, resolved final path from diff: %s", final_path)
        return final_path

    except Exception as exc:
        logger.error("Episode download failed: %s", exc)
        traceback.print_exc()
        raise
    finally:
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
