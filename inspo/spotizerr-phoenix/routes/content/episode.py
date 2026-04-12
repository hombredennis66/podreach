from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
import uuid
import time

from routes.utils.celery_queue_manager import download_queue_manager
from routes.utils.celery_tasks import store_task_info, store_task_status, ProgressState
from routes.utils.get_info import get_client, get_episode
from routes.utils.errors import DuplicateDownloadError
from routes.auth.middleware import require_auth_from_state, User

router = APIRouter()


def construct_spotify_url(item_id: str, item_type: str = "episode") -> str:
    return f"https://open.spotify.com/{item_type}/{item_id}"


@router.get("/download/{episode_id}")
async def handle_download(
    episode_id: str,
    request: Request,
    current_user: User = Depends(require_auth_from_state),
):
    url = construct_spotify_url(episode_id, "episode")

    try:
        client = get_client()
        episode_info = get_episode(client, episode_id)
        if not episode_info or not episode_info.get("name"):
            return JSONResponse(
                content={"error": f"Could not retrieve metadata for episode ID: {episode_id}"},
                status_code=404,
            )

        show = episode_info.get("show") or {}
        name_from_spotify = episode_info.get("name")
        artist_from_spotify = (
            show.get("name")
            or show.get("publisher")
            or "Unknown Show"
        )
    except Exception as exc:
        return JSONResponse(
            content={"error": f"Failed to fetch metadata for episode {episode_id}: {exc}"},
            status_code=500,
        )

    orig_params = dict(request.query_params)
    orig_params["original_url"] = str(request.url)
    try:
        task_id = download_queue_manager.add_task(
            {
                "download_type": "episode",
                "url": url,
                "name": name_from_spotify,
                "artist": artist_from_spotify,
                "username": current_user.username,
                "orig_request": orig_params,
            }
        )
    except DuplicateDownloadError as exc:
        return JSONResponse(
            content={"error": "Duplicate download detected.", "existing_task": exc.existing_task},
            status_code=409,
        )
    except Exception as exc:
        error_task_id = str(uuid.uuid4())
        store_task_info(
            error_task_id,
            {
                "download_type": "episode",
                "url": url,
                "name": name_from_spotify,
                "artist": artist_from_spotify,
                "original_request": orig_params,
                "created_at": time.time(),
                "is_submission_error_task": True,
            },
        )
        store_task_status(
            error_task_id,
            {
                "status": ProgressState.ERROR,
                "error": f"Failed to queue episode download: {exc}",
                "timestamp": time.time(),
            },
        )
        return JSONResponse(
            content={"error": f"Failed to queue episode download: {exc}", "task_id": error_task_id},
            status_code=500,
        )

    return JSONResponse(content={"task_id": task_id}, status_code=202)
