from __future__ import annotations

import enum
from typing import Any

from app.config.settings import AppConfig, config


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CONTROL = "CONTROL"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        return {
            RiskLevel.UNKNOWN: -1,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CONTROL: 4,
        }[self]


class PolicyDecision(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    BLOCK = "BLOCK"


# Per-tool risk policy derived from config.yaml `tool_risks`
RISK_POLICY: dict[str, RiskLevel] = {
    name: RiskLevel(str(level).upper())
    for name, level in config.tool_risks.items()
}


class PermissionEngine:
    def __init__(self, cfg: AppConfig | None = None) -> None:
        app_config = cfg or config
        thresholds = app_config.risk_thresholds
        self.approval_min_risk = RiskLevel(str(thresholds.get("approval_min_risk", "MEDIUM")).upper())
        self.block_min_risk = RiskLevel(str(thresholds.get("block_min_risk", "CONTROL")).upper())
        self.deny_unknown_tools = bool(thresholds.get("deny_unknown_tools", True))
        self.blocked_tools: set[str] = set(thresholds.get("blocked_tools", []))
        self.tool_risks: dict[str, str] = dict(app_config.tool_risks)

    def risk_for(self, tool_name: str) -> RiskLevel:
        raw = self.tool_risks.get(tool_name)
        if raw is None:
            return RiskLevel.UNKNOWN
        return RiskLevel(str(raw).upper())

    def evaluate(
        self,
        tool_name: str,
        context: dict[str, Any] | None = None,
        observer: Any | None = None,
    ) -> PolicyDecision:
        context = context or {}
        zone = context.get("zone")

        if tool_name in self.blocked_tools:
            decision = PolicyDecision.BLOCK
        else:
            decision = self._decide(tool_name, zone)

        if observer is not None:
            observer.log_permission_eval(
                task_id=context.get("task_id"),
                tool_name=tool_name,
                decision=decision.value,
                context={k: v for k, v in context.items() if k != "task_id"},
            )
        return decision

    def _decide(self, tool_name: str, zone: str | None) -> PolicyDecision:
        risk = self.risk_for(tool_name)

        if risk is RiskLevel.UNKNOWN:
            return PolicyDecision.DENY if self.deny_unknown_tools else PolicyDecision.REQUEST_APPROVAL

        if zone == "D":
            return PolicyDecision.BLOCK

        if risk.rank >= self.block_min_risk.rank:
            return PolicyDecision.BLOCK

        if risk.rank >= self.approval_min_risk.rank:
            return PolicyDecision.REQUEST_APPROVAL

        return PolicyDecision.ALLOW