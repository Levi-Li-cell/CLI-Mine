"""
Constitutional safety policy system for the AI Agent harness.

This module implements Constitutional AI principles:
- Machine-readable policy rules
- Policy checks before risky actions
- Refusal or safe alternatives when needed

Usage:
    from safety import Constitution, PolicyChecker, PolicyDecision

    # Load constitution from file
    constitution = Constitution.from_yaml("safety/policies/default.yaml")

    # Check an action
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

__all__ = [
    "PolicyRule",
    "PolicyAction",
    "RiskLevel",
    "Constitution",
    "PolicyDecision",
    "PolicyChecker",
]
