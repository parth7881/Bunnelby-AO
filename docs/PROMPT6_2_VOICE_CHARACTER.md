# Prompt 6 / Phase 6.2 — AO synthetic voice character

Phase 6.2 keeps the approved Phase 6.1 Piper voices and cadence unchanged, then adds
a lightweight, native Web Audio character layer in the Electron renderer. It is an
original AO treatment; it does not clone, imitate, or train on an actor's voice.

## Production signal path

```text
Piper WAV / AudioBufferSource
  -> language EQ
  -> light compressor
  -> dominant dry path -------------------------+
  -> low-level saturation/filter/micro-delay ---+-> final tone -> limiter
  -> tiny filtered ambience --------------------+                  -> analyser
                                                                      -> output
```

The analyser is after the complete treatment, so AO Core motion follows the sound
that reaches the speakers rather than the unprocessed Piper buffer. Each utterance
uses the existing persistent `AudioContext`; only per-playback nodes are created.
`stop()` aborts pending TTS, stops the source, cancels analysis, disconnects every
node, and zeros the Core level immediately.

If the character graph cannot be built, playback falls back to a direct clean Piper
path with a safety gain and final analyser. If Piper or Web Audio also fails, the
full text response remains available and AO continues without speech.

## Profiles

| Profile | Character mix | Ambience | Purpose |
| --- | ---: | ---: | --- |
| `clean` | 0% | 0% | Processed safety baseline; no synthetic path |
| `subtle` | 7.5% | 2.2% | Nearly natural, lightly controlled |
| `cinematic` | 12% | 3.8% | Production default pending listening approval |
| `strong` | 19% | 5.5% | Upper audition boundary, not the default |

The English and Hindi paths share one graph implementation but have independent EQ,
character scaling, ambience scaling, micro-delay offset, and synthetic bandwidth.
Optional language-specific profile and amount overrides allow separate listening
choices without duplicating the engine.

## Configuration

Only `.env.example` documents these values; Phase 6.2 does not rewrite `.env`.

```dotenv
AO_VOICE_CHARACTER_ENABLED=true
AO_VOICE_CHARACTER_PROFILE=cinematic
AO_VOICE_CHARACTER_AMOUNT=

# Optional language-specific overrides; blank inherits the global choice.
AO_VOICE_CHARACTER_EN_PROFILE=
AO_VOICE_CHARACTER_HI_PROFILE=
AO_VOICE_CHARACTER_EN_AMOUNT=
AO_VOICE_CHARACTER_HI_AMOUNT=
```

Amounts are clamped to `0.00`–`0.25`. Invalid profile names fall back to the
configured global profile, then `cinematic`.

## Development audition page

Run the existing API and desktop web development server, then open:

```text
http://127.0.0.1:5173/voice-character-preview.html
```

The page requests real English John and Hindi Rohan audio from `/tts`, then sends it
through the same production player and DSP graph. A/B/C/D select Clean, Subtle,
Cinematic, and Strong. It is excluded from production build entry points and adds no
controls to the AO interface.

Automated tests can prove routing, final-output analysis, interruption cleanup, and
fallback behavior. They cannot decide whether the voice feels natural. The final
English and Hindi choices therefore require listening approval through this page.

Microphone input, wake word, STT, VAD, and acoustic barge-in remain Phase 7 work.
