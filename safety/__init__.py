"""
Constitutional safety policy system for the AI Agent harness.

This module implements Constitutional AI principles:
- Machine-readable policy rules
- Policy checks before risky actions
- Refusal or safe alternatives when needed
- Request-level risk classification
- Sandbox and allowlist for destructive commands

Usage:
    from safety import Constitution, PolicyChecker, RequestClassifier, ShellSandbox

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

    # Evaluate shell command against sandbox
    sandbox = ShellSandbox()
    sandbox_decision = sandbox.evaluate("rm -rf /project/build")
    if sandbox_decision.allowed:
        print(f"Command allowed: {sandbox_decision.reason}")
    else:
        print(f"Command blocked: {sandbox_decision.reason}")
        if sandbox_decision.alternative:
            print(f"Alternative: {sandbox_decision.alternative}")
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
from .sandbox import (
    CommandCategory,
    SandboxMode,
    SandboxDecision,
    CommandRule,
    SandboxConfig,
    ShellSandbox,
    create_default_sandbox,
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
    "CommandCategory",
    "SandboxMode",
    "SandboxDecision",
    "CommandRule",
    "SandboxConfig",
    "ShellSandbox",
    "create_default_sandbox",
]
