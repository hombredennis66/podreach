# Podreach

Find podcast episodes featuring a person, download the audio, transcribe it, and draft a personalized outreach email from the transcript.

## Pipeline

1. **Search** -- Spotify Web API finds episodes by name
2. **Score** -- Claude rates 0-100 whether the person actually appears (vs. just being mentioned)
3. **Download** -- Patched Spotizerr Phoenix instance downloads the episode audio
4. **Transcribe** -- Deepgram nova-2 with speaker diarization
5. **Draft** -- Claude writes a personalized email using the transcript + a template

## Setup

Requires Python >= 3.10.

```
uv sync
cp .env.example .env   # fill in API keys
```

Start the patched Phoenix app in `inspo/spotizerr-phoenix/` before downloading episodes.

## Required Environment

Set these in `.env`:

| Variable | Required | Description |
|---|---|---|
| `SPOTIFY_CLIENT_ID` | yes | Spotify Web API client ID |
| `SPOTIFY_CLIENT_SECRET` | yes | Spotify Web API client secret |
| `SPOTIZERR_URL` | yes | Base URL for the patched Phoenix instance (e.g. `http://localhost:7171`) |
| `SPOTIZERR_TOKEN` | no | Bearer token when Phoenix auth is enabled |
| `SPOTIZERR_DOWNLOADS_DIR` | no | Host path for the Phoenix `./downloads` volume mount so podreach can copy the exact file |
| `DEEPGRAM_API_KEY` | yes | Deepgram API key |
| `ANTHROPIC_API_KEY` | yes | Anthropic API key |

`SPOTIZERR_DOWNLOADS_DIR` should point at the host directory mapped into `/app/downloads` inside the Phoenix container.

## CLI Commands

### `podreach run <name>`

Full pipeline: search, score, download, transcribe, draft.

```
podreach run "Brian Chesky"
podreach run "Tim Ferriss" --template coffee_chat --context "I run a travel startup" --keep-audio
```

| Flag | Default | Description |
|---|---|---|
| `--template, -t` | interactive | `coffee_chat`, `partnership`, or `guest_booking` |
| `--context, -c` | `""` | Context about yourself for email personalization |
| `--limit, -l` | `10` | Number of search results |
| `--keep-audio` | off | Keep audio file after transcription |
| `--verbose, -v` | off | Debug logging |

### `podreach search <name>`

Search Spotify and score episodes only (no download).

```
podreach search "Lex Fridman" --limit 20
```

### `podreach transcribe <audio_file>`

Transcribe a local audio file with speaker diarization.

```
podreach transcribe episode.ogg --output transcript.json
```

### `podreach draft <transcript_file>`

Draft an outreach email from a saved transcript.

```
podreach draft data/brian-airbnb/.../transcript.json --name "Brian Chesky" --template guest_booking
```

## Email Templates

| Key | Description |
|---|---|
| `coffee_chat` | Casual 20-min chat request, warm tone, < 150 words |
| `partnership` | Business collaboration pitch with value prop, < 200 words |
| `guest_booking` | Guest invitation with logistics and topics, < 200 words |

## Data Directory

Each run saves a workspace under `data/{person-slug}/{episode-slug}/`:

```
data/brian-airbnb/unknown-brian-chesky-co-founder-of-airbnb-2023-08-24/
  episode.json       # episode metadata + relevance score
  transcript.json    # speaker-diarized transcript
  *.ogg              # audio file (deleted unless --keep-audio)
```

Transcripts are cached -- re-running the same episode skips download and transcription.

## Episode Download Requirement

Automated episode download depends on the owned Spotizerr Phoenix fork in `inspo/spotizerr-phoenix/`. Stock upstream Phoenix is not sufficient for podcast episode automation in this repo.

The contract:

- `podreach` triggers `GET /api/episode/download/{episode_id}` on the patched Phoenix instance.
- Phoenix returns stable task progress plus `final_path` and `terminal_reason`.
- `podreach` copies the exact downloaded file from `final_path` when possible.

## Project Structure

```
src/podreach/
  cli.py           # Typer CLI with run/search/transcribe/draft commands
  config.py        # Settings from .env (lazy-loaded singleton)
  models.py        # EpisodeResult, ScoredEpisode, Transcript, DraftedEmail
  spotify.py       # Spotify Web API search + token management
  relevance.py     # Claude-based relevance scoring (0-100)
  spotizerr.py     # Spotizerr Phoenix download orchestration + polling
  transcribe.py    # Deepgram nova-2 transcription with diarization
  storage.py       # File storage, caching, slug generation
  draft.py         # Claude email drafting from transcript + template
  templates.py     # Email template definitions
tests/
  test_spotizerr_download.py   # Download module unit tests
```
