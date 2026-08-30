import { Fragment, useEffect, useRef } from 'react';
import ApprovalCard from './ApprovalCard';

function InlineResponseText({ text }) {
  const parts = String(text || '').split(/(\*\*[^*\n]+\*\*)/g);

  return parts.map((part, index) => {
    const isBold = part.startsWith('**') && part.endsWith('**') && part.length > 4;
    if (!isBold) {
      return <Fragment key={`text-${index}`}>{part}</Fragment>;
    }

    return <strong key={`strong-${index}`}>{part.slice(2, -2)}</strong>;
  });
}

function ResponseText({ content }) {
  const sections = String(content || '').split(/\n{2,}/).filter(Boolean);

  return sections.map((section, index) => (
    <p key={`${section.slice(0, 32)}-${index}`}>
      <InlineResponseText text={section} />
    </p>
  ));
}

export default function ResponseSurface({ response, onApprove, onReject }) {
  const surfaceRef = useRef(null);

  useEffect(() => {
    surfaceRef.current?.focus({ preventScroll: true });
  }, [response]);

  if (!response) return null;

  return (
    <section
      ref={surfaceRef}
      className={`response-surface ${response.kind === 'error' ? 'response-surface--error' : ''}`}
      aria-live="polite"
      tabIndex="-1"
    >
      {response.kind === 'approval' ? (
        <ApprovalCard
          title={response.title}
          details={response.details}
          approval={response.approval}
          busy={Boolean(response.approvalBusy)}
          error={response.approvalError || ''}
          decisionMessage={response.decisionMessage || ''}
          onApprove={onApprove}
          onReject={onReject}
        />
      ) : (
        <article className="response-copy">
          {response.kind === 'error' && <p className="response-copy__eyebrow">Connection interrupted</p>}
          <ResponseText content={response.content} />
        </article>
      )}
    </section>
  );
}
