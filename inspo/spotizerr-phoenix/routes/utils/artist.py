import json
from routes.utils.watch.manager import get_watch_config
import logging
from routes.utils.celery_queue_manager import download_queue_manager
from routes.utils.credentials import get_credential, _get_global_spotify_api_creds
from routes.utils.errors import DuplicateDownloadError
from routes.utils.get_info import get_client, get_artist

from deezspot.libutils.utils import get_ids, link_is_valid

# Configure logging
logger = logging.getLogger(__name__)


def log_json(message_dict):
    """Helper function to output a JSON-formatted log message."""
    print(json.dumps(message_dict))


def get_artist_discography(
    url,
    main_spotify_account_name,
    album_type="album,single,compilation,appears_on",
    progress_callback=None,
):
    """
    Validate the URL, extract the artist ID, and retrieve the discography.
    Uses global Spotify API client_id/secret for Spo initialization.
    Args:
        url (str): Spotify artist URL.
        main_spotify_account_name (str): Name of the Spotify account (for context/logging, not API keys for Spo.__init__).
        album_type (str): Types of albums to fetch.
        progress_callback: Optional callback for progress.
    """
    if not url:
        log_json({"status": "error", "message": "No artist URL provided."})
        raise ValueError("No artist URL provided.")

    link_is_valid(link=url)  # This will raise an exception if the link is invalid.

    client_id, client_secret = _get_global_spotify_api_creds()

    if not client_id or not client_secret:
        log_json(
            {
                "status": "error",
                "message": "Global Spotify API client_id or client_secret not configured.",
            }
        )
        raise ValueError("Global Spotify API credentials are not configured.")

    if not main_spotify_account_name:
        # This is a warning now, as API keys are global.
        logger.warning(
            "main_spotify_account_name not provided for get_artist_discography context. Using global API keys."
        )
    else:
        # Check if account exists for context, good for consistency
        try:
            get_credential("spotify", main_spotify_account_name)
            logger.debug(
                f"Spotify account context '{main_spotify_account_name}' exists for get_artist_discography."
            )
        except FileNotFoundError:
            logger.warning(
                f"Spotify account '{main_spotify_account_name}' provided for discography context not found."
            )
        except Exception as e:
            logger.warning(
                f"Error checking Spotify account '{main_spotify_account_name}' for discography context: {e}"
            )

    try:
        artist_id = get_ids(url)
    except Exception as id_error:
        msg = f"Failed to extract artist ID from URL: {id_error}"
        log_json({"status": "error", "message": msg})
        raise ValueError(msg)

    # Fetch artist once and return grouped arrays without pagination
    try:
        client = get_client()
        artist_obj = get_artist(client, artist_id)

        # Normalize groups as arrays of IDs; tolerate dict shape from some sources
        def normalize_group(val):
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                items = val.get("items") or val.get("releases") or []
                return items if isinstance(items, list) else []
            return []

        return {
            "album_group": normalize_group(artist_obj.get("album_group")),
            "single_group": normalize_group(artist_obj.get("single_group")),
            "compilation_group": normalize_group(artist_obj.get("compilation_group")),
            "appears_on_group": normalize_group(artist_obj.get("appears_on_group")),
        }
    except Exception as fetch_error:
        msg = f"An error occurred while fetching the discography: {fetch_error}"
        log_json({"status": "error", "message": msg})
        raise


def download_artist_albums(url, album_type=None, request_args=None, username=None):
    """
    Download albums by an artist, filtered by album types.
    If album_type is not provided, uses the watchedArtistAlbumGroup setting from watch config.

    Args:
        url (str): Spotify artist URL
        album_type (str): Comma-separated list of album types to download
                         (album, single, compilation, appears_on)
                         If None, uses watchedArtistAlbumGroup setting
        request_args (dict): Original request arguments for tracking
        username (str | None): Username initiating the request, used for per-user separation

    Returns:
        tuple: (list of successfully queued albums, list of duplicate albums)
    """
    if not url:
        raise ValueError("Missing required parameter: url")

    artist_id = url.split("/")[-1]
    if "?" in artist_id:
        artist_id = artist_id.split("?")[0]

    logger.info(f"Fetching artist info for ID: {artist_id}")

    if "open.spotify.com" not in url.lower():
        error_msg = (
            "Invalid URL: Artist functionality only supports open.spotify.com URLs"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Get watch config to determine which album groups to download
    valid_groups = {"album", "single", "compilation", "appears_on"}
    if album_type and isinstance(album_type, str):
        requested = [g.strip().lower() for g in album_type.split(",") if g.strip()]
        allowed_groups = [g for g in requested if g in valid_groups]
        if not allowed_groups:
            logger.warning(
                f"album_type query provided but no valid groups found in {requested}; falling back to watch config."
            )
    if not album_type or not isinstance(album_type, str) or not allowed_groups:
        watch_config = get_watch_config()
        allowed_groups = [
            g.lower()
            for g in watch_config.get("watchedArtistAlbumGroup", ["album", "single"])
            if g.lower() in valid_groups
        ]
    logger.info(
        f"Filtering albums by album_type/watch setting (exact album_group match): {allowed_groups}"
    )

    # Fetch artist and aggregate group arrays without pagination
    client = get_client()
    artist_obj = get_artist(client, artist_id)

    def normalize_group(val):
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            items = val.get("items") or val.get("releases") or []
            return items if isinstance(items, list) else []
        return []

    group_key_to_type = [
        ("album_group", "album"),
        ("single_group", "single"),
        ("compilation_group", "compilation"),
        ("appears_on_group", "appears_on"),
    ]

    all_artist_albums = []
    for key, group_type in group_key_to_type:
        ids = normalize_group(artist_obj.get(key))
        # transform to minimal album objects with album_group tagging for filtering parity
        for album_id in ids:
            all_artist_albums.append(
                {
                    "id": album_id,
                    "album_group": group_type,
                }
            )

    # Filter albums based on the allowed types using album_group field (like in manager.py)
    filtered_albums = []
    for album in all_artist_albums:
        album_group_value = album.get("album_group", "").lower()
        album_name = album.get("name", "Unknown Album")
        album_id = album.get("id", "Unknown ID")

        # Exact album_group match only (align with watch manager)
        is_matching_group = album_group_value in allowed_groups

        logger.debug(
            f"Album {album_name} ({album_id}): album_group={album_group_value}. Allowed groups: {allowed_groups}. Match: {is_matching_group}."
        )

        if is_matching_group:
            filtered_albums.append(album)

    if not filtered_albums:
        logger.warning(f"No albums match the specified groups: {allowed_groups}")
        return [], []

    successfully_queued_albums = []
    duplicate_albums = []

    for album in filtered_albums:
        album_id = album.get("id")
        if not album_id:
            logger.warning("Skipping album without ID in filtered list.")
            continue
        # fetch album details to construct URL and names
        try:
            album_obj = download_queue_manager.client.get_album(
                album_id, include_tracks=False
            )  # type: ignore[attr-defined]
        except AttributeError:
            # If download_queue_manager lacks a client, fallback to shared client
            album_obj = get_client().get_album(album_id, include_tracks=False)
        album_url = album_obj.get("external_urls", {}).get("spotify", "")
        album_name = album_obj.get("name", "Unknown Album")
        artists = album_obj.get("artists", []) or []
        album_artist = (
            artists[0].get("name", "Unknown Artist") if artists else "Unknown Artist"
        )

        if not album_url:
            logger.warning(
                f"Skipping album {album_name} because it has no Spotify URL."
            )
            continue

        task_data = {
            "download_type": "album",
            "url": album_url,
            "name": album_name,
            "artist": album_artist,
            "orig_request": request_args,
        }
        if username:
            task_data["username"] = username

        try:
            task_id = download_queue_manager.add_task(task_data)
            successfully_queued_albums.append(
                {
                    "name": album_name,
                    "artist": album_artist,
                    "url": album_url,
                    "task_id": task_id,
                }
            )
        except DuplicateDownloadError as e:
            logger.warning(
                f"Skipping duplicate album {album_name} (URL: {album_url}). Existing task: {e.existing_task}"
            )
            duplicate_albums.append(
                {
                    "name": album_name,
                    "artist": album_artist,
                    "url": album_url,
                    "existing_task": e.existing_task,
                    "message": str(e),
                }
            )
        except Exception as e:
            logger.error(
                f"Failed to queue album {album_name} for an unknown reason: {e}"
            )

    logger.info(
        f"Artist album processing: {len(successfully_queued_albums)} queued, {len(duplicate_albums)} duplicates found from {len(filtered_albums)} matching albums out of {len(all_artist_albums)} total albums."
    )
    return successfully_queued_albums, duplicate_albums
