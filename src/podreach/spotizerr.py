import shutil
import time
from pathlib import Path

import httpx

from podreach import storage


AUDIO_EXTENSIONS = {".mp3", ".ogg", ".flac", ".wav", ".opus", ".m4a"}
SUCCESS_STATUSES = {"done", "complete", "completed", "finished", "100"}
FAILURE_STATUSES = {"error", "failed", "cancelled", "error_retried", "error_auto_cleaned"}


def _headers(token: str) -> dict:
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _snapshot_audio(directory: Path) -> dict[str, tuple[int, int]]:
    snapshot = {}
    if not directory.exists():
        return snapshot

    for file_path in directory.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in AUDIO_EXTENSIONS:
            stat = file_path.stat()
            snapshot[str(file_path.resolve())] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _extract_status(data: dict, last_line: dict) -> str:
    status_info = last_line.get("status_info")
    if isinstance(status_info, dict) and status_info.get("status"):
        return str(status_info["status"]).lower()

    status = last_line.get("status") or data.get("status")
    return str(status or "").lower()


def _extract_terminal_reason(data: dict, last_line: dict) -> str:
    for source in (data, last_line, last_line.get("status_info", {})):
        if not isinstance(source, dict):
            continue
        for key in ("terminal_reason", "error", "message", "reason"):
            value = source.get(key)
            if value:
                return str(value)
    return ""


def _map_remote_final_path(final_path: str, spotizerr_downloads_dir: str) -> Path:
    path = Path(final_path).expanduser()
    if path.exists():
        return path.resolve()

    if not spotizerr_downloads_dir:
        return path

    downloads_root = Path(spotizerr_downloads_dir).expanduser().resolve()
    normalized = str(path).replace("\\", "/")

    for prefix in ("/app/downloads/", "./downloads/", "downloads/"):
        if normalized.startswith(prefix):
            relative = normalized[len(prefix):].lstrip("/")
            return (downloads_root / relative).resolve()

    try:
        return (downloads_root / path.name).resolve()
    except Exception:
        return path


def _resolve_exact_final_path(final_path: str, spotizerr_downloads_dir: str) -> Path | None:
    if not final_path:
        return None

    candidate = _map_remote_final_path(final_path, spotizerr_downloads_dir)
    if candidate.exists():
        return candidate
    return None


def _find_new_audio_from_diff(
    directory: Path,
    before_snapshot: dict[str, tuple[int, int]],
    started_at: float,
) -> list[Path]:
    candidates = []
    if not directory.exists():
        return candidates

    for file_path in directory.rglob("*"):
        if not file_path.is_file() or file_path.suffix.lower() not in AUDIO_EXTENSIONS:
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


def _copy_audio(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return dst


def download_episode(
    spotizerr_url: str,
    spotizerr_token: str,
    episode_id: str,
    dest_dir: Path,
    spotizerr_downloads_dir: str = "",
    timeout: int = 600,
    stall_timeout: int = 120,
) -> Path:
    """Download a podcast episode via a patched Spotizerr Phoenix instance."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    base_url = spotizerr_url.rstrip("/")
    headers = _headers(spotizerr_token)

    downloads_root = Path(spotizerr_downloads_dir).expanduser()
    downloads_snapshot = (
        _snapshot_audio(downloads_root)
        if spotizerr_downloads_dir and downloads_root.exists()
        else {}
    )

    started_at = time.time()
    resp = httpx.get(
        f"{base_url}/api/episode/download/{episode_id}",
        headers=headers,
        timeout=30.0,
    )
    if resp.status_code in (401, 403):
        raise RuntimeError(
            "Spotizerr auth failed. Check SPOTIZERR_URL and SPOTIZERR_TOKEN in .env"
        )
    if resp.status_code not in (200, 202):
        raise RuntimeError(
            f"Spotizerr download failed ({resp.status_code}): {resp.text[:200]}"
        )

    task_data = (
        resp.json()
        if resp.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    task_id = task_data.get("task_id", "")
    if not task_id:
        raise RuntimeError("Spotizerr did not return a task_id")

    last_marker = None
    last_progress_at = time.time()
    latest_final_path = ""
    latest_reason = ""

    while time.time() - started_at < timeout:
        try:
            prgs_resp = httpx.get(
                f"{base_url}/api/prgs/{task_id}",
                headers=headers,
                timeout=10.0,
            )
            if prgs_resp.status_code == 404:
                time.sleep(2)
                continue

            if prgs_resp.status_code == 200:
                data = prgs_resp.json()
                last_line = data.get("last_line", {}) or {}
                status = _extract_status(data, last_line)
                latest_final_path = data.get("final_path") or last_line.get("final_path") or latest_final_path
                latest_reason = _extract_terminal_reason(data, last_line) or latest_reason

                marker = (
                    data.get("status_count"),
                    data.get("timestamp"),
                    status,
                    latest_final_path,
                    latest_reason,
                )
                if marker != last_marker:
                    last_marker = marker
                    last_progress_at = time.time()

                if status in SUCCESS_STATUSES:
                    exact_path = _resolve_exact_final_path(
                        latest_final_path,
                        spotizerr_downloads_dir,
                    )
                    if exact_path:
                        return _copy_audio(exact_path, dest_dir)
                    break

                if status in FAILURE_STATUSES:
                    raise RuntimeError(
                        f"Spotizerr download error: {latest_reason or status}"
                    )

                if time.time() - last_progress_at > stall_timeout:
                    raise RuntimeError(
                        f"Spotizerr task stalled in status '{status or 'unknown'}': "
                        f"{latest_reason or 'no progress update received'}"
                    )
        except httpx.RequestError as exc:
            if time.time() - last_progress_at > stall_timeout:
                raise RuntimeError(
                    f"Spotizerr progress polling stalled after network errors: {exc}"
                ) from exc

        time.sleep(5)

    if time.time() - started_at >= timeout:
        raise RuntimeError(
            f"Spotizerr episode download timed out after {timeout}s. "
            f"Last reason: {latest_reason or 'no terminal status returned'}"
        )

    exact_path = _resolve_exact_final_path(latest_final_path, spotizerr_downloads_dir)
    if exact_path:
        return _copy_audio(exact_path, dest_dir)

    if spotizerr_downloads_dir and downloads_root.exists():
        new_audio_files = _find_new_audio_from_diff(downloads_root, downloads_snapshot, started_at)
        if new_audio_files:
            return _copy_audio(new_audio_files[0], dest_dir)

    audio_files = storage.find_audio_files(dest_dir)
    if audio_files:
        return audio_files[0]

    if latest_reason:
        raise RuntimeError(f"Spotizerr download did not produce audio: {latest_reason}")

    raise RuntimeError(
        "Download completed but file not found. "
        f"Check Spotizerr's downloads directory. Task ID: {task_id}"
    )
