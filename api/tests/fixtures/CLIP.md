# Permissioned speech fixture

No recording is included. To test the worker with Groq transcription, record the following authored text yourself and save it as `owned_sample.wav` here.

> For each event, enforce a unique constraint on the event and seat together. This prevents two bookings for the same seat in the same event.

The text was authored for ReelNotes. It is a synthetic demonstration, not an Instagram transcript. Start with a queued video ID returned by the API, stop the normal worker, then run from `api/`:

```sh
uv run python -m app.import_clip VIDEO_UUID tests/fixtures/owned_sample.wav --owned
```

This command explicitly substitutes a permissioned local recording for this video and labels the title `Owned local sample`. Keep this demo in a disposable local database, and do not represent its source link as verified Instagram evidence. The normal URL importer never substitutes fixture content.

Set `GROQ_API_KEY` in `api/.env` before running the importer. The worker sends the prepared audio to Groq.
