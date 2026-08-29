import { useEffect, useRef } from 'react';
import { createAOCoreScene } from './createAOCoreScene';
import { normalizeCoreProps } from './aoCoreConfig';
import './AOCore.css';

const STATE_LABELS = {
  idle: 'AO Core is awake',
  listening: 'AO Core is listening',
  thinking: 'AO Core is processing',
  speaking: 'AO Core is speaking'
};

export default function AOCore({
  state = 'idle',
  audioLevel = 0,
  size = 'large',
  className = ''
}) {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const propsRef = useRef(normalizeCoreProps({ state, audioLevel, size }));
  propsRef.current = normalizeCoreProps({ state, audioLevel, size });

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = createAOCoreScene(mount, propsRef.current);
    sceneRef.current = scene;
    const observer = new ResizeObserver(([entry]) => {
      scene.resize(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(mount);

    return () => {
      observer.disconnect();
      scene.dispose();
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    sceneRef.current?.update(propsRef.current);
  }, [state, audioLevel, size]);

  const safeProps = propsRef.current;

  return (
    <div
      ref={mountRef}
      className={`ao-core ao-core--${safeProps.size} ${className}`.trim()}
      data-state={safeProps.state}
      data-size={safeProps.size}
      role="img"
      aria-label={STATE_LABELS[safeProps.state]}
    />
  );
}
