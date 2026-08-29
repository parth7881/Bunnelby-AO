# AO UI Direction 01 — Calm Intelligence

## Design system

### Palette

Light:
- Canvas — `#F6F8F7`
- Surface — `#FFFFFF`
- Ink — `#17201F`
- Muted — `#66716F`
- Line — `#DCE4E2`
- Tide — `#0B746E`

Dark:
- Canvas — `#0F1312`
- Surface — `#171C1A`
- Ink — `#F1F5F3`
- Muted — `#A8B3B0`
- Line — `#2A3431`
- Tide — `#60C7BE`

**Why Tide:** teal sits between blue's trust and green's calm, but avoids the violet/indigo shorthand that has become generic for AI products. It is used sparingly for state and focus, not as decoration.

### Typography

- AO responses / headings: `Aptos Display` → `Segoe UI Variable Display` → `Segoe UI`
- Body / controls: `Segoe UI Variable Text` → `Segoe UI` → system sans
- Metadata: `Cascadia Mono` → Consolas

This is intentionally local/system-first: no Google Fonts request, no external font asset, no startup latency. The display face gives AO's responses slightly more voice; body text stays neutral and familiar on Windows; metadata reads as system information without turning the product into a terminal aesthetic.

### Spacing

4px base rhythm: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.

### Radius

8px small, 12px medium, 18px large, pill only for compact controls/status.

## Signature element — AO Trace

AO Trace is a three-stroke abstract mark. It hints at an A rising into an O-like loop without becoming a literal lettermark, face, robot, microphone, Iron-Man reference, or glowing orb.

- **Idle:** almost imperceptible breathing.
- **Listening:** the three strokes flex independently like a quiet voice contour.
- **Thinking:** a moving trace progresses through the paths; nothing spins.
- **Wake:** the strokes draw in once with a restrained overshoot. This is the one special animation moment.

Motion is CSS-only, GPU-light, and disabled under `prefers-reduced-motion`.

## Implementation boundary for Part 1

This package intentionally does **not** change `App.jsx`, the `/chat` request logic, backend routing, or Electron process files. It only adds tokens, the AO mark, and an isolated browser preview. After visual approval, Part 2 can layer the design onto the existing working chat without rewriting its behavior.
