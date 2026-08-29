import './VoiceWave.css';

export default function VoiceWave({ state = 'idle', bars = 18 }) {
  return (
    <div className={`voice-wave voice-wave--${state}`} aria-hidden="true">
      {Array.from({ length: bars }).map((_, index) => (
        <span
          key={index}
          style={{
            '--i': index,
            '--listen-height': `${14 + (index % 5) * 4}px`,
            '--speak-low': `${8 + (index % 3) * 4}px`,
            '--speak-high': `${20 + (index % 6) * 4}px`
          }}
        />
      ))}
    </div>
  );
}
