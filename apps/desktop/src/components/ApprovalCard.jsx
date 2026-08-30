function statusLabel(approval, busy, isCalendar) {
  if (busy) return 'Processing';
  if (!approval) return 'Pending';
  if (approval.status === 'rejected') return 'Rejected';
  if (approval.execution_state === 'completed') return isCalendar ? 'Created' : 'Sent';
  if (approval.execution_state === 'executing') return isCalendar ? 'Creating' : 'Sending';
  if (approval.execution_state === 'failed') return 'Failed';
  if (approval.execution_state === 'unknown') return 'Needs review';
  if (approval.status === 'approved') return 'Approved';
  return 'Pending';
}

function formatDateTime(value) {
  if (!value) return 'Not specified';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString([], {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  });
}

export default function ApprovalCard({
  title,
  details = [],
  approval = null,
  busy = false,
  error = '',
  decisionMessage = '',
  onApprove,
  onReject
}) {
  const isCalendar = Boolean(
    approval && (
      approval.task_type === 'calendar_event'
      || approval.calendar_id
      || (approval.title && approval.start && approval.end)
    )
  );
  const isCompose = approval?.task_type === 'gmail_compose';

  const resolvedTitle = title && title !== 'Review Gmail reply'
    ? title
    : isCalendar
      ? 'Create Calendar Event'
      : isCompose
        ? 'Review New Gmail Message'
        : 'Review Gmail Reply';

  const resolvedDetails = approval
    ? isCalendar
      ? [
          { label: 'Title', value: approval.title || 'Untitled event' },
          { label: 'Start', value: formatDateTime(approval.start) },
          { label: 'End', value: formatDateTime(approval.end) },
          { label: 'Timezone', value: approval.timezone || 'Local timezone' },
          {
            label: 'Attendees',
            value: Array.isArray(approval.attendees) && approval.attendees.length
              ? approval.attendees.join(', ')
              : 'None'
          },
          { label: 'Action', value: 'Create one Calendar event' }
        ]
      : [
          { label: 'To', value: approval.recipient || approval.target || 'Unknown recipient' },
          { label: 'Subject', value: approval.subject || '(no subject)' },
          { label: 'Action', value: isCompose ? 'Send one new Gmail message' : 'Send one Gmail reply' }
        ]
    : details;

  const pending = !approval || approval.status === 'pending';
  const label = statusLabel(approval, busy, isCalendar);
  const approveLabel = busy
    ? 'Processing…'
    : isCalendar
      ? 'Approve & Create'
      : 'Approve & Send';

  return (
    <section className="approval-card" aria-label={isCalendar ? 'Calendar event approval' : 'Gmail approval'}>
      <div className="approval-card__heading">
        <span className="approval-card__signal" aria-hidden="true" />
        <div className="approval-card__heading-copy">
          <p className="approval-card__eyebrow">Human approval required</p>
          <h2>{resolvedTitle}</h2>
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

      {!isCalendar && approval?.preview_content && (
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
            {approveLabel}
          </button>
        </div>
      )}
    </section>
  );
}
