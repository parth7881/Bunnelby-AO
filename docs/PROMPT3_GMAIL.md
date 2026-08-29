# AO Prompt 3 — Gmail Read/Summarize

## Scope

This phase requests only:

`https://www.googleapis.com/auth/gmail.readonly`

No Gmail send, modify, delete, archive, label, or compose logic is implemented.

## Local secret locations

- OAuth Desktop client JSON: `<AO root>/config/google_oauth_client.json` (gitignored)
- Encrypted user token: `%LOCALAPPDATA%/AO/auth/gmail_token.enc` on Windows
- Fernet key: `%LOCALAPPDATA%/AO/auth/fernet.key` on Windows

The OAuth token is encrypted before it is written to disk. The Fernet key is local and separate from the repository. This is appropriate for the MVP but is not equivalent to a hardware-backed OS keystore; Windows DPAPI/Keychain can be added later.

## First-run behavior

The first Gmail request opens the browser. Sign in to the Google account added as a test user and approve the read-only Gmail permission. AO then stores the OAuth token encrypted locally and refreshes access tokens automatically while the refresh token remains valid.

If the Google Auth Platform app is kept in Testing, Google currently limits test-user authorizations (including refresh tokens for non-basic scopes) to 7 days. AO will automatically fall back to browser reauthorization if refresh stops working.

## Manual checks

- `Check my unread emails` -> Gmail read-only, unread inbox, Gemini summary.
- `Summarize my latest emails` -> latest 10 inbox messages, Gemini summary.
- `Send an email to Rahul` -> blocked as read-only in Prompt 3.
