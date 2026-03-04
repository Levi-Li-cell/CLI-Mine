"""
Constitutional safety policy system for the AI Agent harness.

This module implements Constitutional AI principles:
- Machine-readable policy rules
- Policy checks before risky actions
- Refusal or safe alternatives when needed
- Request-level risk classification

Usage:
    from safety import Constitution, PolicyChecker, RequestClassifier

    # Load constitution from file
    constitution = Constitution.from_yaml("safety/policies/default.yaml")

    # Check a tool action
    checker = PolicyChecker(constitution)
    decision = checker.check("shell", {"command": "rm -rf /"})

    if decision.allowed:
        # Proceed with action
        pass
    else:
        # Handle refusal
        print(f"Refused: {decision.reason}")
        if decision.alternative:
            print(f"Suggested alternative: {decision.alternative}")

    # Classify a user request
    classifier = RequestClassifier()
    req_decision = classifier.classify("delete all files on the server")

    if not req_decision.allowed:
        print(f"Request blocked: {req_decision.reasons}")
"""

from .policy import (
    PolicyRule,
    PolicyAction,
    RiskLevel,
    Constitution,
)
from .checker import (
    PolicyDecision,
    PolicyChecker,
)
from .classifier import (
    RiskCategory,
    RiskPattern,
    RequestDecision,
    RequestClassifier,
)

__all__ = [
    "PolicyRule",
    "PolicyAction",
    "RiskLevel",
    "Constitution",
    "PolicyDecision",
    "PolicyChecker",
    "RiskCategory",
    "RiskPattern",
    "RequestDecision",
    "RequestClassifier",
]
