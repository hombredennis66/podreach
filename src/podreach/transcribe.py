from pathlib import Path

from deepgram import DeepgramClient

from podreach.models import Transcript, Utterance


def transcribe_audio(audio_path: Path, api_key: str) -> Transcript:
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    client = DeepgramClient(api_key=api_key)

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    response = client.listen.v1.media.transcribe_file(
        request=audio_data,
        model="nova-2",
        language="en",
        diarize=True,
        punctuate=True,
        utterances=True,
        smart_format=True,
    )

    utterances = []
    if response.results and response.results.utterances:
        for u in response.results.utterances:
            utterances.append(Utterance(
                speaker=u.speaker,
                text=u.transcript,
                start=u.start,
                end=u.end,
            ))

    if not utterances:
        # Fall back to channel transcript
        raw = ""
        if response.results and response.results.channels and response.results.channels.items:
            alts = response.results.channels.items[0].alternatives
            if alts and alts.items:
                raw = alts.items[0].transcript
        return Transcript(utterances=[], raw_text=raw)

    raw_text = "\n".join(f"[Speaker {u.speaker}] {u.text}" for u in utterances)
    return Transcript(utterances=utterances, raw_text=raw_text)
