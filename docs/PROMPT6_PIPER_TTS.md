# Prompt 6 / Phase 6.1 — Local conversational Piper speech

AO keeps the complete assistant response on screen and speaks a separate concise,
voice-optimized `spoken_reply`. Normal conversation produces `reply` and
`spoken_reply` in the same Gemini/Groq generation. Deterministic tool actions prefer
local result-aware speech based on confirmed metadata, so speech never adds a second
model request.

## Runtime configuration

The default voice directory is `%LOCALAPPDATA%\AO\piper\voices`. Override it only
when needed with `PIPER_VOICE_DIR`.

```dotenv
PIPER_ENABLED=true
PIPER_VOICE_DIR=
PIPER_ENGLISH_VOICE=en_US-john-medium
PIPER_HINDI_VOICE=hi_IN-rohan-medium
PIPER_EN_LENGTH_SCALE=1.11
PIPER_HI_LENGTH_SCALE=1.12
```

The length scales are initial, configurable values only. Final cadence requires the
user's listening approval. Phase 6.1 does not pitch-shift, bass-boost, clone, or apply
browser DSP to either voice.

`PIPER_ENABLED=false` disables only `/tts`; `/chat` and text responses continue to
work normally.

## Install Piper

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r services\api\requirements.txt
```

## Download the two voices

Voice files remain outside the Git repository.

```powershell
$voiceDir = "$env:LOCALAPPDATA\AO\piper\voices"
New-Item -ItemType Directory -Force $voiceDir | Out-Null

python -m piper.download_voices `
  --data-dir "$voiceDir" `
  en_US-john-medium

python -m piper.download_voices `
  --data-dir "$voiceDir" `
  hi_IN-rohan-medium

Get-ChildItem "$voiceDir"
```

Expected runtime assets:

```text
en_US-john-medium.onnx
en_US-john-medium.onnx.json
hi_IN-rohan-medium.onnx
hi_IN-rohan-medium.onnx.json
```

## Smoke and A/B tests

The smoke test writes short WAV files to `%TEMP%\AO-piper-smoke`, not the repository.

```powershell
.\.venv\Scripts\python.exe scripts\test_piper.py
```

It synthesizes:

- English: `AO voice systems online.`
- Hindi: `ए ओ वॉइस सिस्टम तैयार है।`

Generate all 24 Phase 6.1 listening samples outside the repository:

```powershell
.\.venv\Scripts\python.exe scripts\test_piper.py --mode ab
```

The default output is `%TEMP%\AO-piper-phase6-1-ab`: four English phrases at
`1.08`, `1.11`, and `1.14`, plus four Hindi phrases at `1.09`, `1.12`, and
`1.15`. Generated WAV files are not source artifacts and must not be committed.

## API behavior

`POST /chat` returns mandatory `reply` plus optional `spoken_reply`,
`spoken_language`, and `action_type`. It temporarily also returns the same text as
`spoken_ack` so Prompt 6 clients remain compatible during migration.

`POST /tts` accepts only `en` or `hi` and at most 600 characters. It returns
`audio/wav`. Piper is imported lazily, and each voice is loaded and cached separately
on first use. Missing Piper, disabled speech, missing models, or synthesis errors do
not affect `/chat`.

The desktop renders `reply` first, prefers `spoken_reply` (falling back to the old
`spoken_ack` field), then requests `/tts` on the next animation frame.
During actual playback, Web Audio measures the WAV waveform through an analyser and
feeds its smoothed RMS level to the existing AO Core. A new command aborts a pending
TTS request, stops the current source, cancels amplitude sampling, and invalidates
stale playback callbacks.

## Spoken-response policy

- Simple questions speak the direct answer, not “Here's the answer.”
- Complex answers keep full detail on screen and speak a 2–4 sentence summary.
- Follow-ups use the existing bounded conversation memory.
- Gmail reports the confirmed unread/recent count; it does not infer importance when
  importance metadata is unavailable.
- Warnings and errors state the failure, impact, and next useful step concisely.
- “Sir” is occasional and is limited to once per short spoken response.
- Markdown, URLs, code blocks, bullets, and overly long output are removed before TTS.
- Hindi/Hinglish is selected per turn and prefers Devanagari for Rohan.
- A small speech-only normalization layer handles common terms such as RAG, API, LLM,
  Gmail, GitHub, and Python without altering screen text.

Microphone capture, STT, wake-word detection, VAD, continuous listening, and acoustic
barge-in remain Phase 7 work. The existing typed-command interruption path is preserved
as its foundation.

Phase 6.2 adds an optional post-Piper Web Audio character layer without changing the
voices or cadence. Its graph, profiles, configuration, audition workflow, and clean
fallback are documented in `docs/PROMPT6_2_VOICE_CHARACTER.md`.

## Licensing note

Review the Piper runtime/project license before commercial distribution. Each voice
model can have separate model-card and license/attribution terms; keep required model
attribution and license information with any distribution. Do not assume that the
runtime license automatically covers a voice model.

- Piper project: https://github.com/OHF-Voice/piper1-gpl
- Piper Python API: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md
- Voice models: https://huggingface.co/rhasspy/piper-voices
