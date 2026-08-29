import { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { createAOVoicePlayer } from './audio/aoVoicePlayer';
import { VOICE_CHARACTER_PROFILES } from './audio/aoVoiceCharacter';
import './voice-character-preview.css';

const PROFILES = [
  { id: 'clean', key: 'A', label: 'Clean', note: 'Safety EQ and dynamics only' },
  { id: 'subtle', key: 'B', label: 'Subtle', note: 'Light machine presence' },
  { id: 'cinematic', key: 'C', label: 'Cinematic', note: 'Production starting point' },
  { id: 'strong', key: 'D', label: 'Strong', note: 'Higher audition intensity' }
];

const PHRASES = {
  en: [
    'Good evening, sir. Everything is running normally.',
    "I've checked your inbox. Two messages need your attention.",
    'The provider is unavailable. Your local services are still running.',
    'R A G retrieves relevant information before generating an answer.'
  ],
  hi: [
    'शुभ संध्या, सर। सभी सिस्टम सामान्य रूप से चल रहे हैं।',
    'मैंने आपका इनबॉक्स देख लिया है। दो संदेश महत्वपूर्ण हैं।',
    'कनेक्शन में समस्या है, लेकिन आपके लोकल सिस्टम सामान्य हैं।',
    'आर ए जी में ए आई पहले संबंधित जानकारी ढूँढता है, फिर जवाब देता है।'
  ]
};

function VoiceCharacterPreview() {
  const [language, setLanguage] = useState('en');
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [profile, setProfile] = useState('cinematic');
  const [speaking, setSpeaking] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [character, setCharacter] = useState({
    mode: 'idle',
    profile: null,
    amount: 0,
    activeNodes: 0
  });
  const [error, setError] = useState('');
  const playerRef = useRef(null);
  const forceDspFailure = new URLSearchParams(window.location.search).get('forceDspFailure') === '1';

  if (!playerRef.current) {
    playerRef.current = createAOVoicePlayer({
      onSpeakingChange: setSpeaking,
      onAudioLevel: setAudioLevel,
      onCharacterChange: setCharacter,
      forceCharacterFailure: forceDspFailure
    });
  }

  useEffect(() => () => {
    void playerRef.current?.dispose();
    playerRef.current = null;
  }, []);

  const selectLanguage = (nextLanguage) => {
    playerRef.current.stop();
    setLanguage(nextLanguage);
    setPhraseIndex(0);
    setError('');
  };

  const selectProfile = (nextProfile) => {
    playerRef.current.stop();
    setProfile(nextProfile);
    setError('');
  };

  const play = async () => {
    setError('');
    try {
      await playerRef.current.unlock();
      const started = await playerRef.current.play({
        text: PHRASES[language][phraseIndex],
        language,
        characterProfile: profile,
        characterAmount: VOICE_CHARACTER_PROFILES[profile].amount,
        characterEnabled: true
      });
      if (!started) setError('Playback could not start. Confirm the local AO API is running.');
    } catch (playbackError) {
      setError(playbackError?.message || 'Playback could not start.');
    }
  };

  const profileDefinition = PROFILES.find((item) => item.id === profile);

  return (
    <main
      className="voice-preview"
      data-language={language}
      data-profile={profile}
      data-speaking={speaking ? 'true' : 'false'}
      data-audio-level={audioLevel.toFixed(4)}
      data-dsp-mode={character.mode}
      data-active-nodes={character.activeNodes || 0}
    >
      <header>
        <p className="eyebrow">Development audition · actual production signal chain</p>
        <h1>AO Voice Character</h1>
        <p className="intro">
          Compare identical Piper speech through the four real-time Web Audio profiles.
          Choose by listening; this page does not alter the production interface.
        </p>
      </header>

      <section className="preview-section" aria-labelledby="language-heading">
        <h2 id="language-heading">Voice</h2>
        <div className="segmented">
          <button
            type="button"
            data-language="en"
            className={language === 'en' ? 'is-active' : ''}
            onClick={() => selectLanguage('en')}
          >
            English · John · 1.11
          </button>
          <button
            type="button"
            data-language="hi"
            className={language === 'hi' ? 'is-active' : ''}
            onClick={() => selectLanguage('hi')}
          >
            Hindi · Rohan · 1.12
          </button>
        </div>
      </section>

      <section className="preview-section" aria-labelledby="profile-heading">
        <h2 id="profile-heading">Character profile</h2>
        <div className="profile-grid">
          {PROFILES.map((item) => (
            <button
              type="button"
              key={item.id}
              data-profile={item.id}
              className={profile === item.id ? 'profile is-active' : 'profile'}
              onClick={() => selectProfile(item.id)}
            >
              <span>{item.key}</span>
              <strong>{item.label}</strong>
              <small>{item.note}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="preview-section" aria-labelledby="phrase-heading">
        <h2 id="phrase-heading">Representative phrase</h2>
        <select
          aria-label="Representative phrase"
          value={phraseIndex}
          onChange={(event) => {
            playerRef.current.stop();
            setPhraseIndex(Number(event.target.value));
          }}
        >
          {PHRASES[language].map((phrase, index) => (
            <option key={phrase} value={index}>{index + 1}. {phrase}</option>
          ))}
        </select>
        <blockquote>{PHRASES[language][phraseIndex]}</blockquote>
      </section>

      <section className="transport" aria-live="polite">
        <div>
          <span className="current-profile">{profileDefinition.key} · {profileDefinition.label}</span>
          <span className="profile-amount">
            character amount {Math.round(VOICE_CHARACTER_PROFILES[profile].amount * 100)}%
          </span>
        </div>
        <div className="meter" aria-label="Processed output level">
          <i style={{ transform: `scaleX(${Math.min(1, audioLevel)})` }} />
        </div>
        <div className="transport-actions">
          <button className="stop" type="button" onClick={() => playerRef.current.stop()}>
            Stop
          </button>
          <button className="play" type="button" onClick={play}>
            {speaking ? 'Restart' : 'Play'}
          </button>
        </div>
      </section>

      <footer>
        <span>DSP: {character.mode}</span>
        <span>Processed RMS: {audioLevel.toFixed(4)}</span>
        {forceDspFailure && <span>Forced DSP failure test</span>}
        {error && <strong role="alert">{error}</strong>}
      </footer>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<VoiceCharacterPreview />);
