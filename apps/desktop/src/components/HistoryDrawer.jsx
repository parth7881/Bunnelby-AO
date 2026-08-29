import { useEffect, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value));
}

export default function HistoryDrawer({ open, exchanges, onClose, reducedMotion }) {
  const closeRef = useRef(null);

  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.button
            className="history-scrim"
            type="button"
            aria-label="Close conversation history"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0.01 : 0.2 }}
          />
          <motion.aside
            id="ao-history"
            className="history-drawer"
            aria-label="Current session history"
            initial={reducedMotion ? { opacity: 0 } : { x: '-104%' }}
            animate={reducedMotion ? { opacity: 1 } : { x: 0 }}
            exit={reducedMotion ? { opacity: 0 } : { x: '-104%' }}
            transition={reducedMotion
              ? { duration: 0.01 }
              : { type: 'spring', stiffness: 280, damping: 34, mass: 0.8 }}
          >
            <header className="history-drawer__header">
              <div>
                <span>Current session</span>
                <strong>History</strong>
              </div>
              <button ref={closeRef} type="button" onClick={onClose} aria-label="Close history">×</button>
            </header>

            <div className="history-drawer__list">
              {exchanges.length === 0 ? (
                <p className="history-drawer__empty">No completed exchanges yet.</p>
              ) : (
                exchanges.map((exchange, index) => (
                  <article className="history-exchange" key={`${exchange.user.time}-${index}`}>
                    <time>{formatTime(exchange.user.time)}</time>
                    <h2>{exchange.user.content}</h2>
                    <p>{exchange.assistant.content}</p>
                  </article>
                ))
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
