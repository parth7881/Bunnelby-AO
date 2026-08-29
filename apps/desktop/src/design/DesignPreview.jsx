import { useEffect, useState } from 'react';
import AOMark from '../components/AOMark';
import './tokens.css';
import './design-preview.css';

const STATES = ['idle', 'listening', 'thinking'];

const SWATCHES = [
  ['Canvas', '--ao-canvas', '#F6F8F7'],
  ['Surface', '--ao-surface', '#FFFFFF'],
  ['Ink', '--ao-ink', '#17201F'],
  ['Muted', '--ao-muted', '#66716F'],
  ['Line', '--ao-line', '#DCE4E2'],
  ['Tide', '--ao-accent', '#0B746E']
];

export default function DesignPreview() {
  const [theme, setTheme] = useState('light');
  const [state, setState] = useState('idle');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    return () => delete document.documentElement.dataset.theme;
  }, [theme]);

  const wake = () => {
    setState('wake');
    window.setTimeout(() => setState('idle'), 900);
  };

  return (
    <main className="design-preview">
      <header className="design-preview__topbar">
        <div>
          <p className="preview-kicker">AO / UI direction 01</p>
          <h1>Calm intelligence, expressed through trace.</h1>
        </div>
        <button
          className="preview-button preview-button--quiet"
          type="button"
          onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')}
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
        >
          {theme === 'light' ? 'Dark preview' : 'Light preview'}
        </button>
      </header>

      <section className="hero-sample" aria-labelledby="mark-title">
        <div className="hero-sample__mark-wrap">
          <AOMark state={state} size={112} />
        </div>
        <div className="hero-sample__copy">
          <p className="preview-kicker">Signature element / AO Trace</p>
          <h2 id="mark-title">One mark. Different system states.</h2>
          <p>
            AO does not glow, spin, or impersonate a robot. Its three restrained
            strokes change tension and drawing rhythm to communicate activity.
          </p>
          <div className="state-controls" aria-label="AO mark state preview">
            {STATES.map((item) => (
              <button
                key={item}
                className="state-chip"
                data-active={state === item}
                type="button"
                onClick={() => setState(item)}
              >
                {item}
              </button>
            ))}
            <button className="state-chip state-chip--wake" type="button" onClick={wake}>
              wake once
            </button>
          </div>
        </div>
      </section>

      <section className="preview-grid">
        <article className="preview-panel">
          <p className="preview-kicker">Palette</p>
          <h2>Tide, not AI-purple.</h2>
          <p className="panel-copy">
            A restrained teal carries system activity. Neutral surfaces do the
            rest, so AO feels trustworthy and quiet rather than themed.
          </p>
          <div className="swatch-list">
            {SWATCHES.map(([name, token, fallback]) => (
              <div className="swatch-row" key={name}>
                <span className="swatch" style={{ background: `var(${token})` }} />
                <span>{name}</span>
                <code>{theme === 'light' ? fallback : token}</code>
              </div>
            ))}
          </div>
        </article>

        <article className="preview-panel typography-panel">
          <p className="preview-kicker">Typography</p>
          <p className="type-display">I found the three messages that need your attention.</p>
          <p className="type-body">
            AO responses use a slightly more editorial display face, while controls
            and supporting information stay neutral and familiar.
          </p>
          <p className="type-meta">ROUTE / GMAIL · 16:42</p>
        </article>

        <article className="preview-panel">
          <p className="preview-kicker">Spacing + radius</p>
          <h2>4px rhythm, soft geometry.</h2>
          <div className="spacing-demo" aria-hidden="true">
            <span style={{ width: '4px' }} />
            <span style={{ width: '8px' }} />
            <span style={{ width: '12px' }} />
            <span style={{ width: '16px' }} />
            <span style={{ width: '24px' }} />
            <span style={{ width: '32px' }} />
            <span style={{ width: '48px' }} />
          </div>
          <div className="radius-demo" aria-hidden="true">
            <span className="radius-demo__sm">8</span>
            <span className="radius-demo__md">12</span>
            <span className="radius-demo__lg">18</span>
          </div>
        </article>

        <article className="preview-panel response-sample">
          <p className="preview-kicker">Response tone</p>
          <div className="response-line" aria-hidden="true" />
          <p className="response-sample__text">
            You are free tomorrow between 2:30 and 4:00 PM.
          </p>
          <p className="response-sample__meta">AO · Calendar check</p>
        </article>
      </section>
    </main>
  );
}
