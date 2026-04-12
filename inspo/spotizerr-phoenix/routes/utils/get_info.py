import os
from typing import Any, Dict, Optional
import os
import threading

from deezspot.libutils import LibrespotClient
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Config helpers to resolve active credentials
from routes.utils.celery_config import get_config_params
from routes.utils.credentials import (
    _get_global_spotify_api_creds,
    get_spotify_blob_path,
    get_spotify_device_info,
)
import logging


# -------- Shared Librespot client (process-wide) --------

_shared_client: Optional[LibrespotClient] = None
_shared_blob_path: Optional[str] = None
_client_lock = threading.RLock()
logger = logging.getLogger(__name__)


def _resolve_blob_path() -> str:
    cfg = get_config_params() or {}
    active_account = cfg.get("spotify")
    if not active_account:
        raise RuntimeError("Active Spotify account not set in configuration.")
    blob_path = get_spotify_blob_path(active_account)
    abs_path = os.path.abspath(str(blob_path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(
            f"Spotify credentials blob not found for account '{active_account}' at {abs_path}"
        )
    return abs_path


def _resolve_device_info(account_name: str):
    device_info = get_spotify_device_info(account_name)
    if device_info:
        logger.info(
            "Using Spotify device info for '%s': name=%s type=%s id=%s locale=%s",
            account_name,
            device_info.get("device_name"),
            device_info.get("device_type"),
            device_info.get("device_id"),
            device_info.get("preferred_locale"),
        )
    else:
        logger.info("No Spotify device info stored for '%s'; using defaults.", account_name)
    return device_info


def get_client() -> LibrespotClient:
    """
    Return a shared LibrespotClient instance initialized from the active account blob.
    Re-initializes if the active account changes.
    """
    global _shared_client, _shared_blob_path
    with _client_lock:
        cfg = get_config_params() or {}
        active_account = cfg.get("spotify")
        if not active_account:
            raise RuntimeError("Active Spotify account not set in configuration.")
        desired_blob = _resolve_blob_path()
        if _shared_client is None or _shared_blob_path != desired_blob:
            try:
                if _shared_client is not None:
                    _shared_client.close()
            except Exception:
                pass
            cfg = get_config_params() or {}
            max_workers = int(cfg.get("librespotConcurrency", 2) or 2)
            device_info = _resolve_device_info(active_account)
            _shared_client = LibrespotClient(
                stored_credentials_path=desired_blob,
                max_workers=max_workers,
                device_info=device_info,
            )
            _shared_blob_path = desired_blob
        return _shared_client


# -------- Thin wrapper API (programmatic use) --------


def create_client(
    credentials_path: str,
    device_info: Optional[Dict[str, Any]] = None,
) -> LibrespotClient:
    """
    Create a LibrespotClient from a librespot-generated credentials.json file.
    """
    abs_path = os.path.abspath(credentials_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Credentials file not found: {abs_path}")
    cfg = get_config_params() or {}
    max_workers = int(cfg.get("librespotConcurrency", 2) or 2)
    return LibrespotClient(
        stored_credentials_path=abs_path,
        max_workers=max_workers,
        device_info=device_info,
    )


def close_client(client: LibrespotClient) -> None:
    """
    Dispose a LibrespotClient instance.
    """
    client.close()


def get_track(client: LibrespotClient, track_in: str) -> Dict[str, Any]:
    """Fetch a track object."""
    return client.get_track(track_in)


def get_album(
    client: LibrespotClient, album_in: str, include_tracks: bool = False
) -> Dict[str, Any]:
    """Fetch an album object; optionally include expanded tracks."""
    return client.get_album(album_in, include_tracks=include_tracks)


def get_artist(client: LibrespotClient, artist_in: str) -> Dict[str, Any]:
    """Fetch an artist object."""
    return client.get_artist(artist_in)


def get_playlist(
    client: LibrespotClient, playlist_in: str, expand_items: bool = False
) -> Dict[str, Any]:
    """Fetch a playlist object; optionally expand track items to full track objects."""
    return client.get_playlist(playlist_in, expand_items=expand_items)


def get_playlist_metadata(playlist_id: str) -> Dict[str, Any]:
    """
    Fetch playlist metadata using the shared client without expanding items.
    """
    client = get_client()
    return get_playlist(client, playlist_id, expand_items=False)


def get_episode(client: LibrespotClient, episode_in: str) -> Dict[str, Any]:
    """Fetch an episode object, preferring the Web API over deprecated extended metadata."""
    if hasattr(client, "get_episode"):
        try:
            return client.get_episode(episode_in)
        except Exception as exc:
            logger.warning("LibrespotClient.get_episode failed for %s: %s", episode_in, exc)

    client_id, client_secret = _get_global_spotify_api_creds()
    if not client_id or not client_secret:
        raise RuntimeError("Global Spotify API credentials are required for episode lookup.")

    spotify = spotipy.Spotify(
        client_credentials_manager=SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
    )
    return spotify.episode(episode_in)
