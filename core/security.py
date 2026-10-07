"""Deterministic secret screening for generated files.

The reviewer is a model; this check is not. A proposed file containing a
credential-shaped value is vetoed before its contents are sent to another
model or written to disk. Findings identify the path and pattern only —
never the suspected secret itself.
"""
from __future__ import annotations

import re

from core.schemas import FilePlan

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("cloud access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("provider API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}={0,2}\b")),
    ("credential assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
]


def scan_file_plan(plan: FilePlan) -> list[str]:
    findings: list[str] = []
    for file in plan.files:
        for label, pattern in _PATTERNS:
            if pattern.search(file.content):
                findings.append(f"{file.path}: possible {label} detected")
    return findings
