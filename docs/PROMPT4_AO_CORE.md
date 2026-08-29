# AO Prompt 4 — Cinematic AO Core

## Orbital fingerprint

AO uses a repeatable asymmetric structure: a tight inner tri-orbit cage, one wider eccentric band, two incomplete inclined arcs, a sparse directional particle halo, and center-originating energy needles. The warm nucleus represents intelligence and outgoing energy; cyan geometry represents sensing, structure, and tool activity.

## Rendering architecture

- Three.js owns one persistent WebGL scene and requestAnimationFrame loop.
- React passes only `state`, `audioLevel`, and `size`; it does not rebuild the scene per audio update.
- Audio amplitude is clamped and smoothed inside the renderer.
- Listening carries waves and particles from the outer field inward.
- Thinking counter-rotates ordered orbital planes and the internal lattice.
- Speaking ignites the nucleus and propagates shells and particles outward.
- Large and docked modes use the same geometry and state language.
- Pixel ratio is capped at 1.5, geometry is shared where practical, and particle fields use buffer geometry.
- ResizeObserver keeps the camera and renderer aligned with Electron window resizing.
- Reduced-motion mode preserves the dimensional composition while nearly stopping continuous motion.

## Public API

```jsx
<AOCore state="idle" audioLevel={0} size="large" />
```

Valid states are `idle`, `listening`, `thinking`, and `speaking`. Valid sizes are `large` and `docked`.

## Preview

From `apps/desktop`, run `npm run dev:web`, then open:

`http://127.0.0.1:5173/ao-core-preview.html`

The preview is intentionally Core-only. A separate developer drawer is hidden by default in the lower-right corner; the backtick key also toggles it, and number keys 1–4 switch states.

## Scope

Prompt 4 does not connect microphone capture, TTS playback, or change the existing AO chat screen. Those systems can feed the same state/audio contract later.
