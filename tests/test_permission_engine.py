from app.config.settings import AppConfig, load_config
from app.core.security import PermissionEngine, PolicyDecision, RiskLevel
from app.services.audit_service import AuditService


def load_engine(overrides: dict | None = None) -> PermissionEngine:
    cfg = load_config()
    if overrides:
        cfg = AppConfig.model_validate(cfg.model_dump() | overrides)
    return PermissionEngine(cfg)


def test_low_risk_tool_allowed():
    engine = load_engine()
    assert engine.evaluate("filesystem.read", {}) is PolicyDecision.ALLOW
    assert engine.evaluate("git.status", {}) is PolicyDecision.ALLOW
    assert engine.evaluate("web.search", {}) is PolicyDecision.ALLOW


def test_medium_risk_requests_approval():
    engine = load_engine()
    assert engine.evaluate("filesystem.write", {}) is PolicyDecision.REQUEST_APPROVAL
    assert engine.evaluate("git.commit", {}) is PolicyDecision.REQUEST_APPROVAL


def test_high_risk_requests_approval_not_blocked():
    engine = load_engine()
    assert engine.evaluate("shell.run", {}) is PolicyDecision.REQUEST_APPROVAL
    assert engine.evaluate("email.send", {}) is PolicyDecision.REQUEST_APPROVAL


def test_blocked_tools_blocked():
    engine = load_engine()
    assert engine.evaluate("credentials.access", {}) is PolicyDecision.BLOCK
    assert engine.evaluate("security.policy_change", {}) is PolicyDecision.BLOCK
    assert engine.evaluate("permission.policy_change", {}) is PolicyDecision.BLOCK


def test_unknown_tool_denied_by_default():
    engine = load_engine()
    assert engine.evaluate("random.unknown_tool", {}) is PolicyDecision.DENY


def test_zone_d_blocks_even_low_risk():
    engine = load_engine()
    assert engine.evaluate("filesystem.read", {"zone": "D"}) is PolicyDecision.BLOCK


def test_zone_c_high_risk_requests_approval():
    engine = load_engine()
    assert engine.evaluate("email.send", {"zone": "C"}) is PolicyDecision.REQUEST_APPROVAL


def test_block_min_risk_configurable():
    engine = load_engine(
        {
            "risk_thresholds": {
                "approval_min_risk": "LOW",
                "block_min_risk": "HIGH",
                "deny_unknown_tools": True,
                "blocked_tools": [],
            }
        }
    )
    assert engine.evaluate("git.commit", {}) is PolicyDecision.REQUEST_APPROVAL
    assert engine.evaluate("email.send", {}) is PolicyDecision.BLOCK
    assert engine.evaluate("security.policy_change", {}) is PolicyDecision.DENY


def test_risk_policy_is_static_authoritative():
    from app.core.security import RISK_POLICY

    assert RISK_POLICY == {
        "filesystem.list": "ALLOW",
        "filesystem.read": "ALLOW",
        "filesystem.write": "REQUEST_APPROVAL",
        "shell.run": "REQUEST_APPROVAL",
        "git.status": "ALLOW",
        "git.diff": "ALLOW",
        "git.commit": "REQUEST_APPROVAL",
        "git.push": "REQUEST_APPROVAL",
        "code.edit": "REQUEST_APPROVAL",
        "test.run": "REQUEST_APPROVAL",
    }
    engine = load_engine()
    assert engine.evaluate("filesystem.list", {}) is PolicyDecision.ALLOW
    assert engine.evaluate("git.push", {}) is PolicyDecision.REQUEST_APPROVAL
    assert engine.evaluate("shell.run", {}) is PolicyDecision.REQUEST_APPROVAL
    assert engine.evaluate("code.edit", {}) is PolicyDecision.REQUEST_APPROVAL
    assert engine.evaluate("test.run", {}) is PolicyDecision.REQUEST_APPROVAL


def test_risk_levels_ranked():
    assert RiskLevel.HIGH.rank > RiskLevel.MEDIUM.rank > RiskLevel.LOW.rank


def test_evaluate_logs_to_observer(db):
    engine = load_engine()
    audit = AuditService(db)
    decision = engine.evaluate("filesystem.write", {"task_id": 1, "zone": "A"}, observer=audit)
    assert decision is PolicyDecision.REQUEST_APPROVAL
    from app.core.models import AuditEvent

    events = db.query(AuditEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "permission_eval"
    assert events[0].action == "filesystem.write"
    assert events[0].decision == "REQUEST_APPROVAL"