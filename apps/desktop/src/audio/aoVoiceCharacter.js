const PROFILE_NAMES = ['clean', 'subtle', 'cinematic', 'strong'];

const BUILD_CONFIG = typeof __AO_VOICE_CHARACTER_CONFIG__ === 'object'
  ? __AO_VOICE_CHARACTER_CONFIG__
  : {};

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

const parseBoolean = (value, fallback) => {
  if (typeof value === 'boolean') return value;
  if (typeof value !== 'string' || !value.trim()) return fallback;
  return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
};

const parseAmount = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? clamp(parsed, 0, 0.25) : null;
};

export const VOICE_CHARACTER_PROFILES = Object.freeze({
  clean: Object.freeze({
    amount: 0,
    ambience: 0,
    delayMs: 0,
    saturation: 0
  }),
  subtle: Object.freeze({
    amount: 0.075,
    ambience: 0.022,
    delayMs: 9,
    saturation: 0.12
  }),
  cinematic: Object.freeze({
    amount: 0.12,
    ambience: 0.038,
    delayMs: 11,
    saturation: 0.22
  }),
  strong: Object.freeze({
    amount: 0.19,
    ambience: 0.055,
    delayMs: 14,
    saturation: 0.36
  })
});

export const VOICE_CHARACTER_LANGUAGE_SETTINGS = Object.freeze({
  en: Object.freeze({
    highpassHz: 72,
    bodyHz: 175,
    bodyDb: 1.25,
    mudHz: 340,
    mudDb: -1.1,
    presenceHz: 2850,
    presenceDb: 1.15,
    airHz: 8600,
    airDb: -0.45,
    characterScale: 1,
    ambienceScale: 1,
    delayOffsetMs: 0,
    syntheticLowpassHz: 5200
  }),
  hi: Object.freeze({
    highpassHz: 66,
    bodyHz: 165,
    bodyDb: 1,
    mudHz: 360,
    mudDb: -0.8,
    presenceHz: 3050,
    presenceDb: 0.75,
    airHz: 9000,
    airDb: -0.65,
    characterScale: 0.88,
    ambienceScale: 0.9,
    delayOffsetMs: 1,
    syntheticLowpassHz: 4800
  })
});

export const VOICE_CHARACTER_COMPRESSOR = Object.freeze({
  threshold: -20,
  knee: 18,
  ratio: 3,
  attack: 0.008,
  release: 0.16
});

export const VOICE_CHARACTER_LIMITER = Object.freeze({
  threshold: -3,
  knee: 0,
  ratio: 20,
  attack: 0.002,
  release: 0.08
});

export function getDefaultVoiceCharacterConfig() {
  const requestedProfile = String(BUILD_CONFIG.profile || 'cinematic').trim().toLowerCase();
  const requestedEnglishProfile = String(BUILD_CONFIG.enProfile || '').trim().toLowerCase();
  const requestedHindiProfile = String(BUILD_CONFIG.hiProfile || '').trim().toLowerCase();
  return {
    enabled: parseBoolean(BUILD_CONFIG.enabled, true),
    profile: PROFILE_NAMES.includes(requestedProfile) ? requestedProfile : 'cinematic',
    amount: parseAmount(BUILD_CONFIG.amount),
    languageProfiles: {
      en: PROFILE_NAMES.includes(requestedEnglishProfile) ? requestedEnglishProfile : null,
      hi: PROFILE_NAMES.includes(requestedHindiProfile) ? requestedHindiProfile : null
    },
    languageAmounts: {
      en: parseAmount(BUILD_CONFIG.enAmount),
      hi: parseAmount(BUILD_CONFIG.hiAmount)
    }
  };
}

export function resolveVoiceCharacterSettings({
  language = 'en',
  enabled,
  profile,
  amount
} = {}) {
  const defaults = getDefaultVoiceCharacterConfig();
  const safeLanguage = language === 'hi' ? 'hi' : 'en';
  const requestedProfile = String(
    profile || defaults.languageProfiles[safeLanguage] || defaults.profile
  ).trim().toLowerCase();
  const safeProfile = PROFILE_NAMES.includes(requestedProfile) ? requestedProfile : defaults.profile;
  const isEnabled = enabled === undefined ? defaults.enabled : Boolean(enabled);
  const profileSettings = VOICE_CHARACTER_PROFILES[safeProfile];
  const explicitAmount = parseAmount(amount);
  const configuredAmount = explicitAmount
    ?? defaults.languageAmounts[safeLanguage]
    ?? defaults.amount;
  const baseAmount = isEnabled ? (configuredAmount ?? profileSettings.amount) : 0;
  const languageSettings = VOICE_CHARACTER_LANGUAGE_SETTINGS[safeLanguage];
  const syntheticAmount = clamp(baseAmount * languageSettings.characterScale, 0, 0.25);

  return {
    enabled: isEnabled,
    language: safeLanguage,
    profile: isEnabled ? safeProfile : 'clean',
    amount: syntheticAmount,
    dryGain: clamp(1 - syntheticAmount, 0.75, 1),
    syntheticGain: syntheticAmount,
    ambienceGain: isEnabled
      ? clamp(profileSettings.ambience * languageSettings.ambienceScale, 0, 0.07)
      : 0,
    microDelaySeconds: isEnabled && syntheticAmount > 0
      ? clamp((profileSettings.delayMs + languageSettings.delayOffsetMs) / 1000, 0.006, 0.018)
      : 0,
    saturation: isEnabled ? profileSettings.saturation : 0,
    eq: languageSettings,
    compressor: VOICE_CHARACTER_COMPRESSOR,
    limiter: VOICE_CHARACTER_LIMITER,
    outputGain: 0.94
  };
}

function configureFilter(context, type, frequency, gain = 0, q = 0.7) {
  const node = context.createBiquadFilter();
  node.type = type;
  node.frequency.value = frequency;
  node.Q.value = q;
  if ('gain' in node) node.gain.value = gain;
  return node;
}

function configureCompressor(context, settings) {
  const node = context.createDynamicsCompressor();
  node.threshold.value = settings.threshold;
  node.knee.value = settings.knee;
  node.ratio.value = settings.ratio;
  node.attack.value = settings.attack;
  node.release.value = settings.release;
  return node;
}

function createSaturationCurve(amount, samples = 1024) {
  const curve = new Float32Array(samples);
  const drive = 1 + amount * 3.5;
  const normalization = Math.tanh(drive);
  for (let index = 0; index < samples; index += 1) {
    const input = (index * 2) / (samples - 1) - 1;
    curve[index] = Math.tanh(input * drive) / normalization;
  }
  return curve;
}

function disconnect(node) {
  try {
    node?.disconnect();
  } catch {
    // Rapid interruption can disconnect the same node more than once.
  }
}

function createFinalOutput(context, inputNode, settings, nodes) {
  const finalTone = configureFilter(context, 'highshelf', 7600, -0.35, 0.7);
  const limiter = configureCompressor(context, settings.limiter);
  const outputGain = context.createGain();
  const analyser = context.createAnalyser();

  outputGain.gain.value = settings.outputGain;
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0;

  inputNode.connect(finalTone);
  finalTone.connect(limiter);
  limiter.connect(outputGain);
  outputGain.connect(analyser);
  analyser.connect(context.destination);

  nodes.push(finalTone, limiter, outputGain, analyser);
  return analyser;
}

export function disconnectVoiceCharacterGraph(graph) {
  if (!graph) return;
  for (const node of [...graph.nodes].reverse()) disconnect(node);
}

export function createCleanFallbackGraph(context, sourceNode, language = 'en') {
  const settings = resolveVoiceCharacterSettings({ language, enabled: false, profile: 'clean', amount: 0 });
  const nodes = [];
  try {
    const safetyGain = context.createGain();
    safetyGain.gain.value = 0.94;
    nodes.push(safetyGain);
    sourceNode.connect(safetyGain);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0;
    nodes.push(analyser);
    safetyGain.connect(analyser);
    analyser.connect(context.destination);
    return {
      mode: 'clean-fallback',
      profile: 'clean',
      settings,
      analyserNode: analyser,
      nodes
    };
  } catch (error) {
    disconnect(sourceNode);
    disconnectVoiceCharacterGraph({ nodes });
    throw error;
  }
}

export function createVoiceCharacterGraph(
  context,
  sourceNode,
  { language, enabled, profile, amount, forceFailure = false } = {}
) {
  if (forceFailure) throw new Error('Forced AO voice-character graph failure.');

  const settings = resolveVoiceCharacterSettings({ language, enabled, profile, amount });
  const nodes = [];

  try {
    const highpass = configureFilter(context, 'highpass', settings.eq.highpassHz, 0, 0.7);
    const body = configureFilter(context, 'peaking', settings.eq.bodyHz, settings.eq.bodyDb, 0.85);
    const mud = configureFilter(context, 'peaking', settings.eq.mudHz, settings.eq.mudDb, 1);
    const presence = configureFilter(
      context,
      'peaking',
      settings.eq.presenceHz,
      settings.eq.presenceDb,
      0.9
    );
    const air = configureFilter(context, 'highshelf', settings.eq.airHz, settings.eq.airDb, 0.7);
    const compressor = configureCompressor(context, settings.compressor);
    const mix = context.createGain();
    const dry = context.createGain();

    dry.gain.value = settings.dryGain;
    nodes.push(highpass, body, mud, presence, air, compressor, mix, dry);

    sourceNode.connect(highpass);
    highpass.connect(body);
    body.connect(mud);
    mud.connect(presence);
    presence.connect(air);
    air.connect(compressor);
    compressor.connect(dry);
    dry.connect(mix);

    if (settings.syntheticGain > 0) {
      const saturation = context.createWaveShaper();
      const syntheticHighpass = configureFilter(context, 'highpass', 145, 0, 0.7);
      const syntheticPresence = configureFilter(context, 'peaking', 1750, 1.1, 1.15);
      const syntheticLowpass = configureFilter(
        context,
        'lowpass',
        settings.eq.syntheticLowpassHz,
        0,
        0.7
      );
      const microDelay = context.createDelay(0.03);
      const syntheticGain = context.createGain();

      saturation.curve = createSaturationCurve(settings.saturation);
      saturation.oversample = '2x';
      microDelay.delayTime.value = settings.microDelaySeconds;
      syntheticGain.gain.value = settings.syntheticGain;
      nodes.push(
        saturation,
        syntheticHighpass,
        syntheticPresence,
        syntheticLowpass,
        microDelay,
        syntheticGain
      );

      compressor.connect(saturation);
      saturation.connect(syntheticHighpass);
      syntheticHighpass.connect(syntheticPresence);
      syntheticPresence.connect(syntheticLowpass);
      syntheticLowpass.connect(microDelay);
      microDelay.connect(syntheticGain);
      syntheticGain.connect(mix);
    }

    if (settings.ambienceGain > 0) {
      const ambienceDelay = context.createDelay(0.06);
      const ambienceLowpass = configureFilter(context, 'lowpass', 4200, 0, 0.7);
      const ambienceGain = context.createGain();

      ambienceDelay.delayTime.value = clamp(
        settings.microDelaySeconds + 0.018,
        0.022,
        0.038
      );
      ambienceGain.gain.value = settings.ambienceGain;
      nodes.push(ambienceDelay, ambienceLowpass, ambienceGain);

      compressor.connect(ambienceDelay);
      ambienceDelay.connect(ambienceLowpass);
      ambienceLowpass.connect(ambienceGain);
      ambienceGain.connect(mix);
    }

    const analyser = createFinalOutput(context, mix, settings, nodes);
    return {
      mode: settings.amount > 0 ? 'character' : 'clean',
      profile: settings.profile,
      settings,
      analyserNode: analyser,
      nodes
    };
  } catch (error) {
    disconnect(sourceNode);
    disconnectVoiceCharacterGraph({ nodes });
    throw error;
  }
}
