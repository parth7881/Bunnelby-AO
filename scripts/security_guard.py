from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    PROJECT_ROOT / "services" / "api" / "app",
    PROJECT_ROOT / "services" / "api" / "scripts",
    PROJECT_ROOT / "apps" / "desktop" / "src",
)
EXTRA_FILES = (
    PROJECT_ROOT / "apps" / "desktop" / "electron.cjs",
    PROJECT_ROOT / "apps" / "desktop" / "preload.cjs",
    PROJECT_ROOT / "apps" / "desktop" / "index.html",
)
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".cjs", ".mjs", ".ts", ".tsx", ".html"}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    description: str
    pattern: re.Pattern[str]


RULES = (
    Rule("BUN001", "Python os.system creates a shell injection surface", re.compile(r"\bos\.system\s*\(")),
    Rule("BUN002", "subprocess shell=True is forbidden", re.compile(r"\bshell\s*=\s*True\b")),
    Rule("BUN003", "JavaScript child_process.exec invokes a shell", re.compile(r"\b(?:child_process\.)?exec\s*\(")),
    Rule("BUN004", "Dynamic eval is forbidden", re.compile(r"\beval\s*\(")),
    Rule("BUN005", "React dangerouslySetInnerHTML requires explicit security review", re.compile(r"\bdangerouslySetInnerHTML\b")),
    Rule("BUN006", "Electron nodeIntegration must never be enabled", re.compile(r"nodeIntegration\s*:\s*true", re.I)),
    Rule("BUN007", "Electron context isolation must never be disabled", re.compile(r"contextIsolation\s*:\s*false", re.I)),
    Rule("BUN008", "Electron webSecurity must never be disabled", re.compile(r"webSecurity\s*:\s*false", re.I)),
    Rule(
        "BUN009",
        "Electron insecure-content execution must never be enabled",
        re.compile(r"allowRunningInsecureContent\s*:\s*true", re.I),
    ),
    Rule("BUN010", "Wildcard FastAPI CORS origin is forbidden", re.compile(r"allow_origins\s*=\s*\[\s*['\"]\*['\"]\s*\]")),
    Rule("BUN011", "Wildcard CORS response header is forbidden", re.compile(r"access-control-allow-origin[^\n]{0,30}\*", re.I)),
)

# High-signal credential formats. Environment-variable names and placeholders are not matches.
SECRET_PATTERNS = (
    Rule("SEC001", "Possible Google API key committed to source", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    Rule("SEC002", "Possible Groq API key committed to source", re.compile(r"\bgsk_[0-9A-Za-z]{20,}\b")),
    Rule("SEC003", "Possible OpenAI-style API key committed to source", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}\b")),
    Rule("SEC004", "Private key material committed to source", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)


def iter_source_files():
    seen: set[Path] = set()
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield path
    for path in EXTRA_FILES:
        if path.is_file() and path.resolve() not in seen:
            yield path


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"READ001 {path.relative_to(PROJECT_ROOT)} is not valid UTF-8 source"]

    failures: list[str] = []
    for rule in (*RULES, *SECRET_PATTERNS):
        match = rule.pattern.search(text)
        if not match:
            continue
        line = text.count("\n", 0, match.start()) + 1
        failures.append(
            f"{rule.rule_id} {path.relative_to(PROJECT_ROOT)}:{line} {rule.description}"
        )
    return failures


def main() -> int:
    failures: list[str] = []
    for path in iter_source_files():
        failures.extend(scan_file(path))

    if failures:
        print("Bunnelby security guard FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "Security rules are fail-closed. Replace the risky primitive with a safer design; "
            "do not suppress the rule without a reviewed security exception.",
            file=sys.stderr,
        )
        return 1

    print("Bunnelby security guard PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
