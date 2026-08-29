function statusLabel(approval, busy) {
  if (busy) return 'Processing';
  if (!approval) return 'Pending';
  if (approval.status === 'rejected') return 'Rejected';
  if (approval.execution_state === 'completed') return 'Sent';
  if (approval.execution_state === 'executing') return 'Sending';
  if (approval.execution_state === 'failed') return 'Failed';
  if (approval.execution_state === 'unknown') return 'Needs review';
  if (approval.status === 'approved') return 'Approved';
  return 'Pending';
}

export default function ApprovalCard({
  title = 'Review Gmail reply',
  details = [],
  approval = null,
  busy = false,
  error = '',
  decisionMessage = '',
  onApprove,
  onReject
}) {
  const resolvedDetails = approval
    ? [
        { label: 'To', value: approval.recipient || approval.target || 'Unknown recipient' },
        { label: 'Subject', value: approval.subject || '(no subject)' },
        { label: 'Action', value: 'Send one Gmail reply' }
      ]
    : details;

  const pending = !approval || approval.status === 'pending';
  const label = statusLabel(approval, busy);

  return (
    <section className="approval-card" aria-label="Gmail reply approval">
      <div className="approval-card__heading">
        <span className="approval-card__signal" aria-hidden="true" />
        <div className="approval-card__heading-copy">
          <p className="approval-card__eyebrow">Human approval required</p>
          <h2>{title}</h2>
        </div>
        <span className={`approval-card__status approval-card__status--${label.toLowerCase().replace(/\s+/g, '-')}`}>
          {label}
        </span>
      </div>

      <div className="approval-card__details">
        {resolvedDetails.map((item) => (
          <div className="approval-row" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      {approval?.preview_content && (
        <div className="approval-card__preview">
          <p className="approval-card__preview-label">Draft preview</p>
          <div className="approval-card__preview-body">{approval.preview_content}</div>
        </div>
      )}

      {decisionMessage && <p className="approval-card__message" role="status">{decisionMessage}</p>}
      {error && <p className="approval-card__error" role="alert">{error}</p>}

      {pending && (
        <div className="approval-card__actions">
          <button
            type="button"
            className="approval-button approval-button--reject"
            onClick={onReject}
            disabled={busy}
          >
            Reject
          </button>
          <button
            type="button"
            className="approval-button approval-button--approve"
            onClick={onApprove}
            disabled={busy}
          >
            {busy ? 'Processing…' : 'Approve & Send'}
          </button>
        </div>
      )}
    </section>
  );
}
