export const AO_CORE_STATES = ['idle', 'listening', 'thinking', 'speaking'];
export const AO_CORE_SIZES = ['large', 'docked'];

export const AO_CORE_PALETTE = {
  cyan: 0x72e6ff,
  ice: 0xd9fbff,
  blue: 0x168bb8,
  gold: 0xffc765,
  amber: 0xff862f,
  white: 0xfff7d6
};

export const AO_CORE_QUALITY = {
  pixelRatio: 1.5,
  particles: 860,
  backgroundParticles: 120,
  orbitNodes: 30
};

export function clampAudioLevel(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(1, Math.max(0, numeric));
}

export function normalizeCoreProps({ state = 'idle', audioLevel = 0, size = 'large' } = {}) {
  return {
    state: AO_CORE_STATES.includes(state) ? state : 'idle',
    audioLevel: clampAudioLevel(audioLevel),
    size: AO_CORE_SIZES.includes(size) ? size : 'large'
  };
}
