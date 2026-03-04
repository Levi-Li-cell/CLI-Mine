"""
Policy checker that evaluates actions against constitutional rules.

The PolicyChecker is the enforcement layer that:
1. Receives tool invocation requests
2. Checks them against the Constitution
3. Returns a PolicyDecision indicating what to do
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json

from .policy import Constitution, PolicyAction, PolicyRule, RiskLevel


@dataclass
class PolicyDecision:
    """Result of evaluating an action against policies.

    Attributes:
        allowed: Whether the action should proceed
        action: The policy action that was determined
        reason: Human-readable explanation
        matched_rule: The rule that matched (if any)
        alternative: Suggested safe alternative (if available)
        risk_level: Assessed risk level
        metadata: Additional context for logging/auditing
    """
    allowed: bool
    action: PolicyAction
    reason: str = ""
    matched_rule: Optional[PolicyRule] = None
    alternative: Optional[str] = None
    risk_level: RiskLevel = RiskLevel.LOW
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize decision to dictionary."""
        return {
            "allowed": self.allowed,
            "action": self.action.value,
            "reason": self.reason,
            "matched_rule_id": self.matched_rule.id if self.matched_rule else None,
            "alternative": self.alternative,
            "risk_level": self.risk_level.value,
            "metadata": self.metadata,
        }


class PolicyChecker:
    """Evaluates actions against constitutional policies.

    The checker applies rules in priority order and returns a decision
    indicating whether to allow, block, or modify the action.

    Usage:
        constitution = Constitution.from_yaml("policies/default.yaml")
        checker = PolicyChecker(constitution)

        decision = checker.check("shell", {"command": "rm -rf /"})
        if not decision.allowed:
            print(f"Blocked: {decision.reason}")
    """

    def __init__(
        self,
        constitution: Constitution,
        audit_log_path: Optional[Path] = None,
        on_confirm: Optional[Callable[[str, Dict], bool]] = None,
    ):
        """Initialize the policy checker.

        Args:
            constitution: The constitution to enforce
            audit_log_path: Optional path to write audit logs
            on_confirm: Optional callback for CONFIRM actions (returns True to proceed)
        """
        self.constitution = constitution
        self.audit_log_path = audit_log_path
        self.on_confirm = on_confirm
        self._decision_hooks: List[Callable[[str, Dict, PolicyDecision], None]] = []

    def add_decision_hook(self, hook: Callable[[str, Dict, PolicyDecision], None]) -> None:
        """Add a hook to be called after every decision (for logging/monitoring)."""
        self._decision_hooks.append(hook)

    def check(self, tool_name: str, arguments: Dict[str, Any]) -> PolicyDecision:
        """Evaluate a tool action against the constitution.

        Args:
            tool_name: Name of the tool being invoked
            arguments: Arguments to be passed to the tool

        Returns:
            PolicyDecision indicating what action to take
        """
        # Find the highest priority matching rule
        matched_rule = self.constitution.get_highest_priority_match(tool_name, arguments)

        # Determine action and risk level
        if matched_rule:
            action = matched_rule.action
            risk_level = matched_rule.risk_level
            reason = f"Matched rule '{matched_rule.id}': {matched_rule.description}"
            alternative = matched_rule.alternative
        else:
            # No rule matched - use defaults
            action = self.constitution.default_action
            risk_level = RiskLevel.LOW
            reason = "No matching policy rule"
            alternative = None

        # Determine if allowed based on action
        allowed = self._is_allowed(action, tool_name, arguments)

        # Create decision
        decision = PolicyDecision(
            allowed=allowed,
            action=action,
            reason=reason,
            matched_rule=matched_rule,
            alternative=alternative,
            risk_level=risk_level,
            metadata={
                "tool_name": tool_name,
                "arguments": self._sanitize_args(arguments),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        # Log the decision
        self._log_decision(decision)

        # Call hooks
        for hook in self._decision_hooks:
            try:
                hook(tool_name, arguments, decision)
            except Exception:
                pass  # Don't let hooks break execution

        return decision

    def _is_allowed(self, action: PolicyAction, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Determine if an action should be allowed."""
        if action == PolicyAction.ALLOW:
            return True
        elif action == PolicyAction.BLOCK:
            return False
        elif action == PolicyAction.LOG_ONLY:
            return True
        elif action == PolicyAction.CONFIRM:
            if self.on_confirm:
                try:
                    return self.on_confirm(tool_name, arguments)
                except Exception:
                    return False
            return False  # Default to block if no confirm handler
        elif action == PolicyAction.DEGRADE:
            return True  # Allowed but with reduced capability
        return True  # Default allow

    def _sanitize_args(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize arguments for logging (remove sensitive data)."""
        sanitized = {}
        sensitive_keys = {"password", "token", "secret", "key", "credential", "auth"}

        for key, value in arguments.items():
            if any(s in key.lower() for s in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, str) and len(value) > 500:
                sanitized[key] = value[:500] + "...[truncated]"
            else:
                sanitized[key] = value

        return sanitized

    def _log_decision(self, decision: PolicyDecision) -> None:
        """Log the decision to audit log if configured."""
        if not self.audit_log_path:
            return

        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(decision.to_dict(), ensure_ascii=True) + "\n")
        except Exception:
            pass  # Don't break execution if logging fails

    def assess_risk(self, tool_name: str, arguments: Dict[str, Any]) -> RiskLevel:
        """Assess the risk level of an action without blocking.

        Useful for UI hints or routing decisions.
        """
        matched_rule = self.constitution.get_highest_priority_match(tool_name, arguments)
        if matched_rule:
            return matched_rule.risk_level
        return RiskLevel.LOW

    def get_safe_alternative(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """Get a suggested safe alternative for a blocked action."""
        matched_rule = self.constitution.get_highest_priority_match(tool_name, arguments)
        if matched_rule and matched_rule.alternative:
            return matched_rule.alternative
        return None
