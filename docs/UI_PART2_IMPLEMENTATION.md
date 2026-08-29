# AO UI Part 2 — Futuristic Command Surface

This update replaces the plain foundation chat screen with the real AO desktop command surface while preserving the existing REST `/chat` logic.

## Visual direction
- Dark cinematic base with cyan/teal system light and a restrained amber permission color.
- Original AO Trace mark retained as the central identity.
- The mark has five visual states: idle, listening, thinking, speaking, wake.
- Speaking is deliberately the most active state: stronger mark motion, rings, and waveform movement.
- Thin grid, scan lines, glass panels, and system readouts create a futuristic assistant feel without copying a film UI exactly.

## Current behavior
- Existing `POST http://127.0.0.1:8000/chat` is unchanged.
- Prompt 2 `Route:` and `Why:` text is parsed and displayed as a structured routing trace.
- While waiting for the backend, AO enters `thinking`.
- When a response arrives, AO enters `speaking` for a short visual response window. This is a visual placeholder until real Piper TTS events are wired in Prompt 8.
- The microphone button previews the listening state only. It does not record audio yet; real voice input is intentionally deferred to Prompt 7.
- ApprovalCard is implemented and exported for Prompt 4/5 integration, but it is not shown by default before approval logic exists.

## No new packages
This update uses React + plain CSS only. No heavy UI framework or animation dependency is added.
