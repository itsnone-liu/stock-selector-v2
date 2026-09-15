from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Decision(str, Enum):
    PASS = "pass"
    REJECT = "reject"
    SKIP = "skip"
    ERROR = "error"


@dataclass(frozen=True)
class Quote:
    code: str
    price: float
    open: float
    previous_close: float
    volume: float | None
    amount: float | None = None
    timestamp: datetime | None = None


@dataclass
class RuleResult:
    decision: Decision
    stage: str
    reason: str
    score: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.decision == Decision.PASS


@dataclass
class DiagnosticCounter:
    total: int = 0
    passed: int = 0
    rejected: int = 0
    skipped: int = 0
    errors: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def add(self, result: RuleResult) -> None:
        self.total += 1
        if result.decision == Decision.PASS:
            self.passed += 1
        elif result.decision == Decision.REJECT:
            self.rejected += 1
        elif result.decision == Decision.SKIP:
            self.skipped += 1
        else:
            self.errors += 1
        self.reasons[result.reason] = self.reasons.get(result.reason, 0) + 1
