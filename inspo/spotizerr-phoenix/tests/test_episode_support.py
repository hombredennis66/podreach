import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from routes.utils.episode_support import (  # noqa: E402
    extract_episode_identity,
    extract_final_path,
    extract_terminal_reason,
    normalize_episode_tags,
    update_episode_retry_state,
)


class EpisodeSupportTests(unittest.TestCase):
    def test_extracts_identity_and_paths_from_nested_callback(self):
        callback = {
            "track": {
                "title": "Episode Title",
                "album": {"title": "Podcast Name"},
            },
            "status_info": {
                "status": "done",
                "final_path": "/app/downloads/podcasts/episode.mp3",
            },
        }

        self.assertEqual(extract_episode_identity(callback), ("Episode Title", "Podcast Name"))
        self.assertEqual(
            extract_final_path(callback),
            "/app/downloads/podcasts/episode.mp3",
        )

    def test_retry_circuit_opens_for_repeated_identical_errors(self):
        task_info = {"url": "https://open.spotify.com/episode/example"}
        callback = {
            "track": {"title": "Episode Title"},
            "status_info": {
                "status": "retrying",
                "error": "Extended Metadata request failed: Status code 404",
                "ids": {"spotify": "episode-id"},
            },
        }

        state, abort_reason = update_episode_retry_state(
            task_info,
            callback,
            now=100,
            repeat_limit=2,
            seconds_limit=90,
        )
        self.assertEqual(state["repeat_count"], 1)
        self.assertEqual(abort_reason, "")

        task_info["episode_retry_circuit"] = state
        _, abort_reason = update_episode_retry_state(
            task_info,
            callback,
            now=110,
            repeat_limit=2,
            seconds_limit=90,
        )
        self.assertIn("Episode retry circuit opened", abort_reason)

    def test_terminal_reason_prefers_nested_status_info(self):
        callback = {
            "message": "outer message",
            "status_info": {
                "status": "error",
                "error": "inner error",
            },
        }
        self.assertEqual(extract_terminal_reason(callback), "inner error")

    def test_normalize_episode_tags_populates_name_and_show_aliases(self):
        normalized = normalize_episode_tags(
            {
                "music": "Brian Chesky (co-founder of airbnb)",
                "album": "Armchair Expert with Dax Shepard",
                "artist": "Armchair Umbrella",
            }
        )

        self.assertEqual(normalized["name"], "Brian Chesky (co-founder of airbnb)")
        self.assertEqual(normalized["show"], "Armchair Expert with Dax Shepard")
        self.assertEqual(
            normalized["episode_name"],
            "Brian Chesky (co-founder of airbnb) - Armchair Expert with Dax Shepard",
        )


if __name__ == "__main__":
    unittest.main()
