import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from podreach.spotizerr import download_episode  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._payload


class SpotizerrDownloadTests(unittest.TestCase):
    def test_prefers_exact_final_path_from_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads_dir = Path(tmpdir) / "downloads"
            dest_dir = Path(tmpdir) / "dest"
            downloads_dir.mkdir()
            exact_file = downloads_dir / "episode.mp3"
            exact_file.write_text("episode-audio")
            (downloads_dir / "unrelated.mp3").write_text("other")

            def fake_get(url, **kwargs):
                if url.endswith("/api/episode/download/episode-id"):
                    return FakeResponse(202, {"task_id": "task-1"})
                if url.endswith("/api/prgs/task-1"):
                    return FakeResponse(
                        200,
                        {
                            "task_id": "task-1",
                            "status_count": 2,
                            "timestamp": 123,
                            "final_path": str(exact_file),
                            "last_line": {"status": "done"},
                        },
                    )
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("podreach.spotizerr.httpx.get", side_effect=fake_get):
                with mock.patch("podreach.spotizerr.time.sleep", return_value=None):
                    output = download_episode(
                        "http://spotizerr.test",
                        "",
                        "episode-id",
                        dest_dir,
                        spotizerr_downloads_dir=str(downloads_dir),
                        timeout=10,
                        stall_timeout=10,
                    )

            self.assertEqual(output.name, "episode.mp3")
            self.assertEqual(output.read_text(), "episode-audio")

    def test_falls_back_to_directory_diff_when_final_path_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads_dir = Path(tmpdir) / "downloads"
            dest_dir = Path(tmpdir) / "dest"
            downloads_dir.mkdir()
            (downloads_dir / "old.mp3").write_text("old-audio")

            created = {"done": False}

            def fake_get(url, **kwargs):
                if url.endswith("/api/episode/download/episode-id"):
                    return FakeResponse(202, {"task_id": "task-2"})
                if url.endswith("/api/prgs/task-2"):
                    if not created["done"]:
                        created["done"] = True
                        (downloads_dir / "new-episode.mp3").write_text("new-audio")
                    return FakeResponse(
                        200,
                        {
                            "task_id": "task-2",
                            "status_count": 2,
                            "timestamp": 456,
                            "last_line": {"status": "done"},
                        },
                    )
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("podreach.spotizerr.httpx.get", side_effect=fake_get):
                with mock.patch("podreach.spotizerr.time.sleep", return_value=None):
                    output = download_episode(
                        "http://spotizerr.test",
                        "",
                        "episode-id",
                        dest_dir,
                        spotizerr_downloads_dir=str(downloads_dir),
                        timeout=10,
                        stall_timeout=10,
                    )

            self.assertEqual(output.name, "new-episode.mp3")
            self.assertEqual(output.read_text(), "new-audio")


if __name__ == "__main__":
    unittest.main()
