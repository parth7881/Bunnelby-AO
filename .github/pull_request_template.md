## Change summary

Describe what changed and why.

## Security review — required

Every box must be considered. If an item does not apply, mark it N/A and explain briefly.

- [ ] Trust boundary identified: renderer / local runtime / external service / untrusted content.
- [ ] Inputs are allow-list validated for type, size, format, range, path/URL, and encoding as applicable.
- [ ] No authorization or approval decision relies only on frontend state or model output.
- [ ] Risk level (R0-R5) is unchanged or explicitly documented; model output cannot lower it.
- [ ] External writes/destructive operations use deterministic approval and idempotency controls.
- [ ] Email, webpage, document, OCR, tool, and model content is treated as untrusted data and cannot grant capabilities.
- [ ] No hard-coded secret, token, credential, private key, or sensitive test fixture was added.
- [ ] Logs/errors do not expose secrets, tokens, personal content, stack traces, or internal paths unnecessarily.
- [ ] No new shell execution, `eval`, unsafe deserialization, disabled TLS verification, wildcard CORS, or insecure Electron setting was introduced.
- [ ] Filesystem and URL handling prevents traversal/SSRF/symlink or reparse-point abuse where applicable.
- [ ] New dependency is necessary, locked, license-reviewed where relevant, and install scripts are minimized.
- [ ] Privacy impact reviewed: local/cloud routing, retention, microphone/screen/camera data, and least privilege.
- [ ] Negative/security tests cover rejection, malformed input, failure, replay/race, and unauthorized paths where relevant.
- [ ] `python scripts/security_guard.py` passes.
- [ ] Backend regression tests pass.
- [ ] Dependency/static-analysis CI gates pass.

## Consequential-action snapshot

If this change can send, create, modify, delete, call, upload, purchase, or alter system state, document:

- exact action:
- risk level:
- approval rule:
- idempotency/replay protection:
- rollback/failure behavior:

## Manual validation

Document the live test performed, especially for Windows, Electron, microphone, filesystem, browser, OAuth, or Android behavior.
