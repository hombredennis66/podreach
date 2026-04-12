import re
from typing import List
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
import logging

# Import authentication dependencies
from routes.auth.middleware import require_auth_from_state, User

# Import queue management and Spotify info
from routes.utils.celery_queue_manager import download_queue_manager

# Import authentication dependencies

# Import queue management and Spotify info
from routes.utils.get_info import (
    get_client,
    get_track,
    get_album,
    get_playlist,
    get_artist,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class BulkAddLinksRequest(BaseModel):
    links: List[str]


@router.post("/bulk-add-spotify-links")
async def bulk_add_spotify_links(
    request: BulkAddLinksRequest,
    req: Request,
    current_user: User = Depends(require_auth_from_state),
):
    added_count = 0
    failed_links = []
    total_links = len(request.links)

    client = get_client()
    for link in request.links:
        # Assuming links are pre-filtered by the frontend,
        # but still handle potential errors during info retrieval or unsupported types
        # Extract type and ID from the link directly using regex
        match = re.match(
            r"https://open\.spotify\.com(?:/[a-z]{2})?/(track|album|playlist|artist)/([a-zA-Z0-9]+)(?:\?.*)?",
            link,
        )
        if not match:
            logger.warning(
                f"Could not parse Spotify link (unexpected format after frontend filter): {link}"
            )
            failed_links.append(link)
            continue

        spotify_type = match.group(1)
        spotify_id = match.group(2)
        logger.debug(
            f"Extracted from link: spotify_type={spotify_type}, spotify_id={spotify_id}"
        )
        logger.debug(
            f"Extracted from link: spotify_type={spotify_type}, spotify_id={spotify_id}"
        )

        try:
            # Get basic info to confirm existence and get name/artist
            if spotify_type == "playlist":
                item_info = get_playlist(client, spotify_id, expand_items=False)
            elif spotify_type == "track":
                item_info = get_track(client, spotify_id)
            elif spotify_type == "album":
                item_info = get_album(client, spotify_id)
            elif spotify_type == "artist":
                # Not queued below, but fetch to validate link and name if needed
                item_info = get_artist(client, spotify_id)
            else:
                logger.warning(
                    f"Unsupported Spotify type: {spotify_type} for link: {link}"
                )
                failed_links.append(link)
                continue

            item_name = item_info.get("name", "Unknown Name")
            artist_name = ""
            if spotify_type in ["track", "album"]:
                artists = item_info.get("artists", [])
                if artists:
                    artist_name = ", ".join(
                        [a.get("name", "Unknown Artist") for a in artists]
                    )
            elif spotify_type == "playlist":
                owner = item_info.get("owner", {})
                artist_name = owner.get("display_name", "Unknown Owner")

            # Construct URL for the download task
            spotify_url = f"https://open.spotify.com/{spotify_type}/{spotify_id}"

            # Prepare task data for the queue manager
            task_data = {
                "download_type": spotify_type,
                "url": spotify_url,
                "name": item_name,
                "artist": artist_name,
                "spotify_id": spotify_id,
                "type": spotify_type,
                "username": current_user.username,
                "orig_request": dict(req.query_params),
            }

            # Add to download queue using the queue manager
            task_id = download_queue_manager.add_task(task_data)

            if task_id:
                added_count += 1
                logger.debug(
                    f"Added {added_count}/{total_links} {spotify_type} '{item_name}' ({spotify_id}) to queue with task_id: {task_id}."
                )
            else:
                logger.warning(
                    f"Failed to add {spotify_type} '{item_name}' ({spotify_id}) to queue."
                )
                failed_links.append(link)
                continue

        except Exception as e:
            logger.error(f"Error processing Spotify link {link}: {e}", exc_info=True)
            failed_links.append(link)

    message = f"Successfully added {added_count}/{total_links} links to queue."
    if failed_links:
        message += f" Failed to add {len(failed_links)} links."
        logger.warning(f"Bulk add completed with {len(failed_links)} failures.")
    else:
        logger.info(f"Bulk add completed successfully. Added {added_count} links.")

    return {
        "message": message,
        "count": added_count,
        "failed_links": failed_links,
    }
