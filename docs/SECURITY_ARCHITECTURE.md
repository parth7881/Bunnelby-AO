# Bunnelby Secure-by-Design Architecture

Status: living security architecture. Every feature must preserve these controls unless a reviewed design explicitly replaces them with a stronger control.

## Why this exists

Rapid AI-assisted development can produce software that appears correct while silently omitting authorization, validation, secret handling, dependency hygiene, or abuse controls. Bunnelby has unusually high impact because it can read private context and eventually control email, calendar, files, browser state, and parts of Windows. Security therefore has to be designed into the architecture rather than added after features are complete.

The baseline is informed by OWASP ASVS 5.0 / OWASP Top 10, NIST SP 800-218 SSDF, CISA Secure by Design, Electron's security guidance, GitHub dependency/code/secret scanning, and OpenSSF supply-chain practices.

## Trust zones

### Zone 0 — deterministic security kernel

Must never be controlled by an LLM:

- runtime ON/OFF state;
- tool registry permissions;
- risk classification;
- approval requirements;
- path/URL/command allow-lists;
- OAuth scopes;
- local/cloud data-routing policy;
- secret access;
- execution idempotency;
- resource/time/output limits.

### Zone 1 — local privileged runtime

FastAPI/runtime supervisor, encrypted credentials, SQLite, microphone/VAD/wake-word services, screen/UI automation, filesystem tools, and approved external connectors. Treat requests entering this zone as untrusted until validated.

### Zone 2 — Electron renderer

The renderer is unprivileged and potentially compromiseable. It must not receive Node integration or direct secret access. IPC/API calls are capability-limited and validated by Zone 1.

### Zone 3 — external/cloud systems

Gmail, Calendar, Gemini/Groq, web resources, model registries, package registries, and future connectors. All content returned from these systems is untrusted data. Cloud use must be explicit, bounded, and privacy-filtered.

### Zone 4 — content controlled by third parties

Emails, webpages, documents, attachments, retrieved text, model/tool output, OCR, and screen content. These can contain prompt injection or malicious payloads. They never authorize an action.

## Core control model

Bunnelby uses a deterministic risk ladder:

- **R0** harmless local/read-only operation: automatic after validation.
- **R1** personal-data read: only within granted permission/scope and privacy policy.
- **R2** reversible local mutation: configurable approval depending on scope.
- **R3** external communication/write: explicit approval of exact immutable snapshot.
- **R4** destructive or difficult-to-reverse action: strong explicit confirmation plus narrow execution contract.
- **R5** financial, credential/security-policy, privileged administration: blocked by default until separately designed and hardened.

Model/tool prompts cannot downgrade a risk level.

## Current implemented controls

- secrets and OAuth JSON excluded from Git;
- Gmail tokens stored outside the repository and encrypted at rest;
- bounded Gmail context and draft sizes;
- prompt-injection instructions treat email content as untrusted;
- Gmail send and Calendar create require durable approval records;
- approved preview/target snapshot is revalidated before execution;
- compare-and-set execution state and idempotency protections reduce duplicate/race execution;
- local STT/VAD assets stay outside Git and ordinary audio is temporary;
- React output uses normal React text rendering rather than raw HTML injection;
- renderer CSP limits network connections to the local backend/dev server;
- Electron context isolation + sandbox + disabled Node integration/webview/navigation/window creation;
- browser-origin / Fetch Metadata checks on the local API;
- request body limits and strict chat/TTS validation;
- API docs disabled by default;
- deterministic insecure-code scanner;
- Python/Node dependency auditing, Bandit, CodeQL, regression tests, Dependabot.

## Required hardening roadmap

### S0 — Shift-left security baseline — IN PROGRESS

- [x] Security invariants and vulnerability policy.
- [x] Deterministic dangerous-primitive/secret guard.
- [x] CodeQL for Python + JavaScript/TypeScript.
- [x] Python `pip-audit` and Bandit gates.
- [x] npm high-severity audit and locked build gate.
- [x] Dependabot configuration.
- [x] Electron baseline hardening.
- [x] Browser-to-localhost abuse boundary and request-size caps.
- [ ] CI and local regression verification after this baseline commit set.
- [ ] Confirm GitHub secret scanning + push protection + private vulnerability reporting are enabled in repository settings.

### S1 — authenticated local control channel

Before Bunnelby becomes always-on/background capable:

- runtime generates a cryptographically random per-launch secret/capability;
- secret is never hard-coded, logged, committed, or exposed to arbitrary pages;
- Electron obtains only the capability required for its session through protected IPC/runtime bootstrap;
- privileged API endpoints reject unauthenticated local processes/pages;
- capability is rotated each launch and invalid after runtime shutdown;
- CORS remains narrow but is not treated as authentication;
- rate/concurrency limits prevent local resource exhaustion.

Long-term preference: move privileged renderer communication from open localhost REST to authenticated Electron IPC or an OS-protected local transport, keeping HTTP only where actually necessary.

### S2 — secret and local-data protection

- migrate Fernet key protection toward Windows DPAPI / OS credential vault where practical;
- establish key rotation/revocation procedure;
- redact secrets/tokens/personal content from logs;
- classify stored memory by sensitivity and retention;
- encrypt particularly sensitive local artifacts;
- secure deletion/retention behavior for audio, screenshots, temporary files, model inputs;
- prohibit secrets from being included in LLM prompts unless the connector protocol absolutely requires them.

### S3 — tool capability security

Every tool implements a structured contract:

- typed input schema;
- size/range/format allow-list validation;
- explicit capability/risk classification;
- timeout and cancellation;
- output-size cap;
- deterministic evidence/result validation;
- audit event without secrets;
- no direct LLM access to unrestricted OS primitives.

Tool failures must fail closed.

### S4 — terminal and filesystem security

Terminal is not a generic shell.

- no `shell=True`, `os.system`, PowerShell command-string execution, or JavaScript shell `exec`;
- argv-based executable allow-list;
- read-only commands first;
- dangerous flags/subcommands denied;
- canonicalize and restrict working directories;
- block path traversal, device paths, UNC/network paths unless explicitly supported;
- environment allow-list rather than inheriting all secrets;
- process timeout, CPU/output limits, child-process cleanup;
- R3/R4 approval for mutations/destructive operations;
- never execute command text originating from webpages/email/documents without explicit trusted user intent and policy validation.

Filesystem tools similarly use canonical paths, bounded file sizes, extension/content checks, symlink/reparse-point defenses, and explicit roots.

### S5 — browser/web and SSRF security

- URL parser with `https` default;
- hostname/IP validation;
- block localhost, loopback, link-local, private networks, metadata endpoints, file/data/javascript protocols for generic web fetches;
- DNS rebinding protections for server-side fetches;
- response byte/time/redirect caps;
- sandbox untrusted HTML; never inject raw third-party HTML into privileged renderer;
- browser automation follows official API/DOM bridge before visual clicks;
- browser content remains untrusted prompt data.

### S6 — prompt injection / agent security

- separate trusted instruction from untrusted context structurally;
- tool calls are generated as typed proposals, not executable strings;
- policy engine validates proposed tool + parameters independently of model reasoning;
- external content cannot alter system prompts, tool permissions, recipients, scopes, or approvals;
- provenance/evidence retained for consequential decisions;
- high-impact actions require exact preview and immutable approval snapshot;
- no self-modifying code or autonomous permission expansion.

### S7 — supply chain and build integrity

- lock all production dependencies and review upgrades;
- reject high/critical vulnerable dependencies unless a documented temporary exception exists;
- minimize install scripts and package count;
- GitHub Actions pinned to immutable commit SHAs;
- least-privilege workflow permissions;
- generate SBOM before release;
- sign Windows release artifacts and verify update signatures before enabling auto-update;
- protected release process and reproducible build targets;
- OpenSSF Scorecard review before public production releases.

### S8 — verification before production

Security Definition of Done for each meaningful feature:

1. threat boundary identified;
2. inputs/outputs/sensitive data classified;
3. least privilege selected;
4. abuse cases and prompt-injection path considered;
5. deterministic authorization/approval implemented;
6. negative/security tests added;
7. dependency/security gates pass;
8. no secret/log leakage;
9. failure path fails closed;
10. manual live validation completed for hardware/OS-specific behavior.

Before release, add focused penetration testing for local API abuse, Electron compromise, OAuth/token theft, prompt injection, tool escalation, filesystem traversal, command injection, SSRF, approval replay/races, update-chain compromise, and privacy leakage.

## AI-assisted development rule

AI-generated code is treated exactly like code from an untrusted new contributor: useful, but not trusted merely because it compiles or passes a happy-path demo. Every generated change must satisfy this architecture, deterministic guardrails, tests, and human-visible approval boundaries.
