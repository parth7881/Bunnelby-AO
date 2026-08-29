import { useEffect, useState } from 'react';
import AOCore from '../components/AOCore';
import './ao-core-preview.css';

const STATES = ['idle', 'listening', 'thinking', 'speaking'];

function getInitialPreview() {
  const params = new URLSearchParams(window.location.search);
  const requestedState = params.get('state');
  const requestedSize = params.get('size');
  const requestedAudio = Number(params.get('audio'));
  return {
    state: STATES.includes(requestedState) ? requestedState : 'idle',
    size: requestedSize === 'docked' ? 'docked' : 'large',
    audioLevel: Number.isFinite(requestedAudio) ? Math.min(1, Math.max(0, requestedAudio)) : 0.55
  };
}

export default function AOCorePreview() {
  const [initialPreview] = useState(getInitialPreview);
  const [state, setState] = useState(initialPreview.state);
  const [audioLevel, setAudioLevel] = useState(initialPreview.audioLevel);
  const [size, setSize] = useState(initialPreview.size);
  const [debugOpen, setDebugOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === '`') setDebugOpen((current) => !current);
      if (event.key >= '1' && event.key <= '4') setState(STATES[Number(event.key) - 1]);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <main className="core-hero">
      <div className="core-hero__atmosphere" aria-hidden="true" />
      <section className="core-hero__stage" aria-label="AO Core cinematic preview">
        <AOCore state={state} audioLevel={audioLevel} size={size} />
      </section>

      <details
        className="debug-drawer"
        open={debugOpen}
        onToggle={(event) => setDebugOpen(event.currentTarget.open)}
      >
        <summary aria-label="Toggle AO Core developer controls">
          <span aria-hidden="true" />
        </summary>
        <div className="debug-drawer__panel">
          <div className="debug-drawer__group" aria-label="Core state">
            {STATES.map((item) => (
              <button
                key={item}
                type="button"
                data-active={state === item}
                onClick={() => setState(item)}
              >
                {item}
              </button>
            ))}
          </div>

          <label className="debug-drawer__level">
            <span>Audio</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={audioLevel}
              onChange={(event) => setAudioLevel(Number(event.target.value))}
            />
            <output>{audioLevel.toFixed(2)}</output>
          </label>

          <div className="debug-drawer__group" aria-label="Core size">
            <button type="button" data-active={size === 'large'} onClick={() => setSize('large')}>Large</button>
            <button type="button" data-active={size === 'docked'} onClick={() => setSize('docked')}>Docked</button>
          </div>
        </div>
      </details>
    </main>
  );
}
