import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from pathlib import Path

from podreach.config import get_settings
from podreach.models import EpisodeResult, ScoredEpisode, Transcript
from podreach.templates import TEMPLATES

app = typer.Typer(help="Podcast-based outreach automation")
console = Console()


def display_episodes(scored_episodes: list[ScoredEpisode]) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Rel.", width=5)
    table.add_column("Episode Title", max_width=50)
    table.add_column("Podcast", max_width=25)
    table.add_column("Date", width=12)
    table.add_column("Duration", width=10)

    for i, se in enumerate(scored_episodes, 1):
        ep = se.episode
        minutes = ep.duration_ms // 60000
        seconds = (ep.duration_ms % 60000) // 1000
        duration = f"{minutes}:{seconds:02d}"

        score_str = f"{se.relevance_score}%"
        style = "dim" if se.relevance_score < 30 else None

        table.add_row(
            str(i), score_str, ep.title[:50], ep.show_name[:25],
            ep.release_date, duration, style=style,
        )

    console.print(table)


def display_transcript_preview(transcript: Transcript, max_lines: int = 8) -> None:
    preview = transcript.formatted(max_utterances=max_lines)
    if len(transcript.utterances) > max_lines:
        preview += f"\n... ({len(transcript.utterances) - max_lines} more utterances)"
    console.print(Panel(preview, title="Transcript Preview", border_style="blue"))


def display_email(email) -> None:
    content = f"[bold]Subject:[/bold] {email.subject}\n\n{email.body}"
    console.print(Panel(content, title="Drafted Email", border_style="green"))


def pick_template() -> str:
    console.print("\nChoose template:")
    for i, (key, tmpl) in enumerate(TEMPLATES.items(), 1):
        console.print(f"  {i}. {tmpl['name']} - {tmpl['description']}")
    choice = IntPrompt.ask("Select", choices=[str(i) for i in range(1, len(TEMPLATES) + 1)])
    return list(TEMPLATES.keys())[choice - 1]


@app.command()
def run(
    name: str = typer.Argument(help="Person's name to search (e.g. 'Tim Ferriss', 'bryan airbnb founder')"),
    template: str = typer.Option(None, "--template", "-t", help="Email template (coffee_chat, partnership, guest_booking)"),
    context: str = typer.Option("", "--context", "-c", help="Context about yourself for email personalization"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of search results"),
    keep_audio: bool = typer.Option(False, "--keep-audio", help="Keep audio file after transcription"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Full pipeline: search -> download -> transcribe -> draft email."""
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    settings = get_settings()

    # Step 1: Search Spotify for podcast episodes
    from podreach.spotify import search_episodes
    console.print(f"\nSearching Spotify for episodes featuring [bold]{name}[/bold]...")
    episodes = search_episodes(settings.spotify_client_id, settings.spotify_client_secret, name, limit)
    if not episodes:
        console.print("[red]No episodes found. Try a different search query.[/red]")
        raise typer.Exit(1)

    # Step 2: Score relevance
    from podreach.relevance import score_episodes
    console.print("Scoring relevance...")
    scored = score_episodes(settings.anthropic_api_key, name, episodes)

    display_episodes(scored)

    # Step 3: Select episode
    choice = IntPrompt.ask(
        "Select episode",
        choices=[str(i) for i in range(1, len(scored) + 1)],
    )
    selected = scored[choice - 1]
    ep = selected.episode

    # Step 4: Check cache or download + transcribe
    from podreach import storage
    episode_dir = storage.get_episode_dir(settings.download_dir, name, ep)
    storage.save_episode_metadata(episode_dir, ep, selected.relevance_score, name)

    if storage.has_transcript(episode_dir):
        console.print("[green]Transcript cached, skipping download & transcription.[/green]")
        transcript = storage.load_transcript(episode_dir)
    else:
        # Download via Spotizerr Phoenix
        from podreach.spotizerr import download_episode
        console.print("Downloading via Spotizerr...")
        try:
            audio_path = download_episode(
                settings.spotizerr_url, settings.spotizerr_token,
                ep.id, episode_dir,
                spotizerr_downloads_dir=settings.spotizerr_downloads_dir,
            )
            size_mb = audio_path.stat().st_size / (1024 * 1024)
            console.print(f"Downloaded: {audio_path.name} ({size_mb:.1f} MB)")
        except Exception as e:
            console.print(f"[red]Download failed: {e}[/red]")
            raise typer.Exit(1)

        # Transcribe with Deepgram
        from podreach.transcribe import transcribe_audio
        console.print("Transcribing (Deepgram nova-2 + diarization)...")
        try:
            transcript = transcribe_audio(audio_path, settings.deepgram_api_key)
        except Exception as e:
            console.print(f"[red]Transcription failed: {e}[/red]")
            raise typer.Exit(1)

        speakers = len(set(u.speaker for u in transcript.utterances))
        console.print(f"Done. {len(transcript.utterances)} utterances, {speakers} speakers.")

        storage.save_transcript(episode_dir, transcript)

        if not keep_audio:
            storage.cleanup_audio(episode_dir)
            console.print("[dim]Audio deleted (use --keep-audio to retain).[/dim]")

    display_transcript_preview(transcript)

    # Step 5: Analyze transcript + Draft email with Claude
    from podreach.draft import analyze_transcript, draft_email

    episode_meta = storage.load_episode_metadata(episode_dir)

    console.print("Analyzing transcript for insights...")
    insights = analyze_transcript(
        settings.anthropic_api_key, transcript, name, episode_meta,
    )
    console.print(Panel(insights.formatted(), title="Transcript Insights", border_style="yellow"))

    if template is None:
        template = pick_template()

    if not context:
        context = Prompt.ask("Context about yourself? (optional, Enter to skip)", default="")

    console.print("Drafting email...")
    email = draft_email(
        settings.anthropic_api_key, transcript, episode_meta,
        name, template, context,
    )

    display_email(email)
    console.print(f"\n[dim]Saved: {episode_dir}/[/dim]")


@app.command()
def search(
    name: str = typer.Argument(help="Person's name to search"),
    limit: int = typer.Option(10, "--limit", "-l", help="Number of results"),
) -> None:
    """Search Spotify for podcast episodes featuring a person."""
    settings = get_settings()

    from podreach.spotify import search_episodes
    from podreach.relevance import score_episodes

    console.print(f"\nSearching Spotify for episodes featuring [bold]{name}[/bold]...")
    episodes = search_episodes(settings.spotify_client_id, settings.spotify_client_secret, name, limit)
    if not episodes:
        console.print("[red]No episodes found.[/red]")
        raise typer.Exit(1)

    console.print("Scoring relevance...")
    scored = score_episodes(settings.anthropic_api_key, name, episodes)
    display_episodes(scored)


@app.command()
def transcribe(
    audio_file: Path = typer.Argument(help="Path to audio file"),
    output: Path = typer.Option(None, "--output", "-o", help="Output path for transcript JSON"),
) -> None:
    """Transcribe a local audio file with speaker diarization."""
    settings = get_settings()

    from podreach.transcribe import transcribe_audio
    import json

    console.print(f"Transcribing {audio_file.name}...")
    transcript = transcribe_audio(audio_file, settings.deepgram_api_key)

    speakers = len(set(u.speaker for u in transcript.utterances))
    console.print(f"Done. {len(transcript.utterances)} utterances, {speakers} speakers.")
    display_transcript_preview(transcript)

    out_path = output or audio_file.with_suffix(".json")
    out_path.write_text(json.dumps(transcript.to_dict(), indent=2))
    console.print(f"Saved to: {out_path}")


@app.command()
def draft(
    transcript_file: Path = typer.Argument(help="Path to transcript JSON file"),
    name: str = typer.Option(..., "--name", "-n", help="Person's name"),
    template: str = typer.Option(None, "--template", "-t", help="Template type"),
    context: str = typer.Option("", "--context", "-c", help="Context about yourself"),
) -> None:
    """Draft an outreach email from a saved transcript."""
    settings = get_settings()

    from podreach.models import Transcript
    from podreach.draft import draft_email
    import json

    transcript_data = json.loads(transcript_file.read_text())
    transcript = Transcript.from_dict(transcript_data)

    # Try to load episode metadata from same directory
    episode_meta = {}
    episode_json = transcript_file.parent / "episode.json"
    if episode_json.exists():
        episode_meta = json.loads(episode_json.read_text())

    if template is None:
        template = pick_template()

    if not context:
        context = Prompt.ask("Context about yourself? (optional, Enter to skip)", default="")

    console.print("Drafting email...")
    email = draft_email(
        settings.anthropic_api_key, transcript, episode_meta,
        name, template, context,
    )
    display_email(email)


if __name__ == "__main__":
    app()
