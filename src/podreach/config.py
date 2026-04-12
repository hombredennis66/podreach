from dataclasses import dataclass, fields, MISSING
import os

from dotenv import load_dotenv


@dataclass
class Settings:
    spotify_client_id: str
    spotify_client_secret: str
    spotizerr_url: str
    deepgram_api_key: str
    anthropic_api_key: str
    spotizerr_token: str = ""
    spotizerr_downloads_dir: str = ""
    download_dir: str = "./data"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        kwargs = {}
        missing = []
        for f in fields(cls):
            env_key = f.name.upper()
            val = os.getenv(env_key)
            if val is not None:
                kwargs[f.name] = val
            elif f.default is not MISSING:
                kwargs[f.name] = f.default
            else:
                missing.append(env_key)
        if missing:
            raise RuntimeError(
                f"Missing environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in your API keys."
            )
        return cls(**kwargs)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
