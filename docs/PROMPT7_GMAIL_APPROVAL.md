# Prompt 7 — Gmail Reply Drafting + Human Approval + Safe Send

## Scope

Prompt 7 extends the existing Gmail read integration with **reply drafting and explicit human approval**. It does not add unrestricted compose, forwarding, delete/archive, labels, or other Gmail mutations.

User-facing assistant identity is **Bunnelby**. Legacy internal identifiers such as `AOCore`, the `AO` repository folder, and `%LOCALAPPDATA%\AO` runtime paths remain unchanged to avoid regressions.

## OAuth change

Requested scopes are now:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.send`

An encrypted token created during the read-only phase does not contain `gmail.send`. On the first Gmail use after this upgrade, `gmail_service._load_credentials()` detects the old scope set, removes only the encrypted OAuth token, and starts the existing browser consent flow again. The Fernet key and OAuth client JSON are not exposed or rewritten.

If manual recovery is ever needed on Windows, close Bunnelby and remove only:

```powershell
Remove-Item "$env:LOCALAPPDATA\AO\auth\gmail_token.enc" -ErrorAction SilentlyContinue
```

Then start the backend and use Gmail again. Google consent should open once.

## Draft flow

```text
User reply request
  -> existing Gmail intent route
  -> resolve an existing inbox thread conservatively
  -> fetch full thread context
  -> sanitize/bound thread data
  -> Gemini-only draft_reply(thread_id, instruction)
  -> persist immutable approval snapshot (status=pending)
  -> /chat returns approval metadata
  -> Prompt 5 response-expanded layout renders ApprovalCard
```

`draft_reply()` never calls Gmail send.

The approval snapshot stores the exact:

- thread id
- source message id
- RFC Message-ID / References where available
- recipient
- subject
- draft body
- original user instruction
- spoken language

The draft body displayed in the card is the same body enforced at send time.

## Human decision states

Human decision `status` remains one of:

- `pending`
- `approved`
- `rejected`

Execution is tracked separately:

- `not_started`
- `executing`
- `completed`
- `failed`
- `unknown`

This keeps the human decision auditable while still allowing an atomic execution claim.

## Absolute send boundary

There is one production Gmail send boundary:

```text
POST /approvals/{id}/approve
  -> approval_service.approve_and_execute(id)
  -> approval_service.send_approved_email(id)
  -> verify status == approved
  -> validate immutable preview/target snapshot
  -> atomic DB claim: not_started -> executing
  -> gmail_service._send_reply_payload(snapshot)
  -> Gmail users.messages.send(...)
```

No frontend-supplied recipient, subject, or body is accepted by the approve endpoint.

The exact security/idempotency claim is a conditional database update requiring all of:

```text
approval.id == requested id
approval.status == "approved"
approval.execution_state == "not_started"
approval.executed_at IS NULL
```

Only the request that changes exactly one row owns the send. Duplicate approve requests cannot acquire the claim twice.

## Double-send / uncertain-send strategy

The execution claim is committed **before** Gmail is called. Therefore, after a network/process problem, another approve request cannot simply resend.

If Gmail returns a confirmed success, execution becomes `completed` and the Gmail message/thread ids are recorded.

If the outcome is uncertain, execution becomes `unknown` (or remains safely non-retriable if local finalization itself failed). Bunnelby does **not** auto-retry an uncertain send because that could create a duplicate.

## Reply threading

The low-level send constructs MIME with:

- `To` (RFC `Reply-To` is preferred over `From` when present)
- normalized `Re:` subject
- `In-Reply-To` when the source RFC Message-ID exists
- `References` when available
- plain-text body

The Gmail `threadId` is included in `users.messages.send`, so the reply remains in the original Gmail thread.

## Frontend

The existing Prompt 5 `ApprovalCard` is now wired to real approval data in the response-expanded center area. `AOCore` remains the same persistent component and docks using the existing layout.

The card shows:

- recipient
- subject
- exact draft preview
- status
- Approve & Send
- Reject
- safe result/error state

The frontend is not a security boundary; all decision and send enforcement occurs in the backend.

After confirmed send, the existing local voice path speaks a deterministic short acknowledgement such as `Sent, sir.` No extra LLM call is used.

## Migration

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m alembic -c database\alembic.ini upgrade head
```

This applies `0003_create_approvals.py`.

## Manual test

1. Start backend and frontend.
2. Ask: `Reply to Rahul's latest email and tell him I'll review the build tonight.`
3. Complete one-time Google reauthorization if the browser opens.
4. Confirm an approval card appears and no message is sent yet.
5. Verify recipient, subject, and draft body.
6. Click **Reject** on one test draft and verify nothing sends.
7. Create another draft and click **Approve & Send** exactly once.
8. Confirm Gmail shows one reply in the original thread.
9. Verify Bunnelby speaks the short send acknowledgement.

Do not test with important recipients until the preview and rejection path have been validated first.
