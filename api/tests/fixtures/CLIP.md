# Permissioned speech fixture

No real clip is included. To exercise actual local speech recognition, record the following authored text yourself and save it as `owned_sample.wav` here:

> For each event, enforce a unique constraint on the event and seat together. This prevents two bookings for the same seat in the same event.

The text was authored for ReelNotes. It is a synthetic demonstration, not an Instagram transcript. Start with a queued video ID returned by the API, stop the normal worker, then run from `api/`:

```sh
uv run python -m app.import_clip VIDEO_UUID tests/fixtures/owned_sample.wav --owned
```

This command explicitly substitutes a permissioned local recording for this video and labels the title `Owned local sample`. Keep this demo in a disposable local database, and do not represent its source link as verified Instagram evidence. The normal URL importer never substitutes fixture content.

On 2026-11-14, macOS speech synthesis returned an empty audio file and the Alex voice was unavailable. The empty file was removed. FFmpeg and Whisper transcription of a real clip have not been verified.
