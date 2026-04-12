import base64
import time

import httpx

from podreach.models import EpisodeResult


_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_access_token(client_id: str, client_secret: str) -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {credentials}"},
        data={"grant_type": "client_credentials"},
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Spotify auth failed ({resp.status_code}). Check SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET."
        )
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600) - 60
    return _token_cache["token"]


def search_episodes(client_id: str, client_secret: str, query: str, limit: int = 10) -> list[EpisodeResult]:
    """Search Spotify Web API for podcast episodes."""
    token = _get_access_token(client_id, client_secret)
    resp = httpx.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": query, "type": "episode", "limit": limit},
    )
    if resp.status_code == 401:
        _token_cache["token"] = None
        raise RuntimeError("Spotify auth expired. Try again.")
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "30")
        raise RuntimeError(f"Spotify rate limited. Retry after {retry_after}s.")
    if resp.status_code != 200:
        raise RuntimeError(f"Spotify search failed ({resp.status_code}): {resp.text[:300]}")

    items = resp.json().get("episodes", {}).get("items", [])

    # Batch fetch episode details to get show names (search returns show=null in dev mode)
    episode_ids = [item["id"] for item in items if item]
    show_map = _batch_get_show_names(token, episode_ids) if episode_ids else {}

    results = []
    for item in items:
        if item is None:
            continue
        show = item.get("show", {}) or {}
        ep_id = item["id"]
        show_info = show_map.get(ep_id, {})
        results.append(EpisodeResult(
            id=ep_id,
            title=item.get("name", "Unknown"),
            show_name=show.get("name") or show_info.get("name", "Unknown"),
            show_id=show.get("id") or show_info.get("id", ""),
            description=item.get("description", ""),
            release_date=item.get("release_date", ""),
            duration_ms=item.get("duration_ms", 0),
            spotify_url=item.get("external_urls", {}).get("spotify", ""),
        ))
    return results


def _batch_get_show_names(token: str, episode_ids: list[str]) -> dict:
    """Fetch episode details in batches to get show names."""
    show_map = {}
    # Spotify allows up to 50 IDs per request
    for i in range(0, len(episode_ids), 50):
        batch = episode_ids[i:i + 50]
        try:
            resp = httpx.get(
                "https://api.spotify.com/v1/episodes",
                headers={"Authorization": f"Bearer {token}"},
                params={"ids": ",".join(batch)},
            )
            if resp.status_code == 200:
                for ep in resp.json().get("episodes", []):
                    if ep and ep.get("show"):
                        show_map[ep["id"]] = {
                            "name": ep["show"].get("name", ""),
                            "id": ep["show"].get("id", ""),
                        }
        except httpx.RequestError:
            pass
    return show_map
