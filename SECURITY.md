# Bunnelby Security Policy

Bunnelby is a local-first desktop assistant with access to sensitive local context and external accounts. Security is therefore a product requirement, not a post-release cleanup task.

## Security invariants

These rules are fail-closed and apply to every future feature, including AI-generated or rapidly prototyped code:

1. **Local-first and least privilege.** Bind local services to loopback. Request only the minimum OAuth/API/OS permissions required for the current feature.
2. **No implicit external writes.** Email sends, calendar writes, filesystem mutations, and other consequential actions require the appropriate deterministic risk gate and explicit approval. Model output never grants approval.
3. **Untrusted data stays data.** Email, files, webpages, retrieved documents, tool output, model output, and IPC/network payloads cannot override system policy or authorize tools.
4. **No hard-coded secrets.** API keys, OAuth tokens, passwords, signing keys, and private keys must not be committed. Runtime secrets live outside Git and are encrypted or OS-protected where practical.
5. **Strict input boundaries.** Validate type, size, format, range, encoding, identifiers, paths, URLs, and command arguments at trust boundaries.
6. **No shell-by-default execution.** `os.system`, `shell=True`, JavaScript shell `exec`, dynamic `eval`, and equivalent primitives are prohibited. Future terminal capabilities must use an allow-listed argv-based executor with timeouts, working-directory restrictions, output caps, and risk classification.
7. **Electron isolation stays enabled.** `contextIsolation=true`, `nodeIntegration=false`, `sandbox=true`, `webSecurity=true`, no arbitrary navigation/windows/webviews, and explicit permission handling.
8. **No frontend-only authorization.** Permission and approval enforcement is server/runtime-side and deterministic.
9. **No raw continuous surveillance upload.** Wake word, VAD, rolling microphone buffers, and routine screen/context processing remain local by default. Cloud transmission must be bounded, purpose-specific, and policy-controlled.
10. **Security checks are build gates.** Tests, deterministic guardrails, dependency auditing, static analysis, and CodeQL must remain part of the development process.

## Threat model priorities

Bunnelby treats the following as high-priority threats:

- malicious webpages driving requests to localhost;
- prompt injection from Gmail, documents, webpages, retrieved text, or tool output;
- confused-deputy behavior where an LLM attempts a tool action outside user intent;
- approval tampering, replay, duplicate execution, or race conditions;
- OAuth/API token theft;
- malicious or compromised dependencies / install scripts;
- Electron renderer compromise and privilege escalation;
- command/path/SQL/template injection;
- SSRF and unsafe URL fetching;
- arbitrary filesystem traversal or destructive terminal commands;
- sensitive data leakage to logs, Git, cloud LLMs, or UI error messages;
- denial of service through oversized or intentionally expensive inputs;
- compromised update/build artifacts.

## Vulnerability reporting

Do not publish active vulnerabilities, secrets, access tokens, or exploit details in a public issue. Revoke/rotate any exposed credential immediately and preserve only the minimum evidence needed to diagnose the problem.

Until a dedicated private reporting channel is configured, repository maintainers should use GitHub's private vulnerability reporting/security-advisory features where available.

## Secure development references

The project security baseline is aligned to OWASP ASVS 5.0, OWASP Top 10, NIST SP 800-218 SSDF, CISA Secure by Design, Electron's official security checklist, and GitHub/OpenSSF supply-chain guidance.
