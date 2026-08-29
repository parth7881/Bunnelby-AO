import './AOMark.css';

const LABELS = {
  idle: 'AO is ready',
  listening: 'AO is listening',
  thinking: 'AO is thinking',
  speaking: 'AO is speaking',
  wake: 'AO is awake'
};

export default function AOMark({ state = 'idle', size = 88, className = '' }) {
  const safeState = Object.hasOwn(LABELS, state) ? state : 'idle';

  return (
    <span
      className={`ao-mark ao-mark--${safeState} ${className}`.trim()}
      role="img"
      aria-label={LABELS[safeState]}
      data-state={safeState}
      style={{ '--ao-mark-size': `${size}px` }}
    >
      <span className="ao-mark__halo ao-mark__halo--outer" aria-hidden="true" />
      <span className="ao-mark__halo ao-mark__halo--inner" aria-hidden="true" />
      <svg
        className="ao-mark__svg"
        viewBox="0 0 80 80"
        width={size}
        height={size}
        aria-hidden="true"
        focusable="false"
      >
        <path className="ao-mark__stroke ao-mark__stroke--rise" pathLength="1" d="M16 54C22 37 28 23 38 16" />
        <path className="ao-mark__stroke ao-mark__stroke--bridge" pathLength="1" d="M24 43C34 39 43 39 53 42" />
        <path className="ao-mark__stroke ao-mark__stroke--loop" pathLength="1" d="M43 18C57 18 65 27 65 39C65 52 56 61 44 61C35 61 28 56 24 49" />
      </svg>
    </span>
  );
}
