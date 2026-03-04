"""
Request classifier for risk assessment of user inputs.

This module provides request-level risk classification that analyzes
user messages/intents BEFORE any tools are invoked. This complements
the tool-level policies in checker.py.

Key features:
1. Pattern-based risk classification (low/medium/high/critical)
2. Gating for high-risk requests (block or require confirmation)
3. Audit logging of all classifications
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern
import json
import re

from .policy import RiskLevel


class RiskCategory(Enum):
    """Categories of risky request patterns."""
    SYSTEM_DESTRUCTION = "system_destruction"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    CREDENTIAL_ACCESS = "credential_access"
    NETWORK_ATTACK = "network_attack"
    ARBITRARY_EXECUTION = "arbitrary_execution"
    SECURITY_BYPASS = "security_bypass"
    SENSITIVE_ACCESS = "sensitive_access"
    UNSAFE_OPERATION = "unsafe_operation"


@dataclass
class RiskPattern:
    """A pattern for detecting risky requests.

    Attributes:
        id: Unique identifier
        category: Category of risk
        risk_level: Assessed risk level when pattern matches
        patterns: List of regex patterns to match against request text
        keywords: List of keywords that indicate this risk (case-insensitive)
        description: Human-readable description
        action: Recommended action (block, confirm, log_only)
        requires_confirmation: Whether this requires user confirmation
    """
    id: str
    category: RiskCategory
    risk_level: RiskLevel
    patterns: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    description: str = ""
    action: str = "log_only"
    requires_confirmation: bool = False

    _compiled_patterns: List[Pattern] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self):
        self._compiled_patterns = []
        for pattern in self.patterns:
            try:
                self._compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                pass

    def matches(self, text: str) -> bool:
        """Check if this pattern matches the given text."""
        text_lower = text.lower()

        # Check keyword matches
        for keyword in self.keywords:
            if keyword.lower() in text_lower:
                return True

        # Check regex patterns
        for compiled in self._compiled_patterns:
            if compiled.search(text):
                return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "category": self.category.value,
            "risk_level": self.risk_level.value,
            "patterns": self.patterns,
            "keywords": self.keywords,
            "description": self.description,
            "action": self.action,
            "requires_confirmation": self.requires_confirmation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskPattern":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            category=RiskCategory(data.get("category", "unsafe_operation")),
            risk_level=RiskLevel(data.get("risk_level", "medium")),
            patterns=data.get("patterns", []),
            keywords=data.get("keywords", []),
            description=data.get("description", ""),
            action=data.get("action", "log_only"),
            requires_confirmation=data.get("requires_confirmation", False),
        )


@dataclass
class RequestDecision:
    """Result of classifying a user request.

    Attributes:
        risk_level: Overall assessed risk level
        allowed: Whether the request should be allowed to proceed
        matched_patterns: List of patterns that matched
        reasons: List of reasons for the classification
        requires_confirmation: Whether user confirmation is needed
        metadata: Additional context for logging
    """
    risk_level: RiskLevel
    allowed: bool = True
    matched_patterns: List[RiskPattern] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "risk_level": self.risk_level.value,
            "allowed": self.allowed,
            "matched_pattern_ids": [p.id for p in self.matched_patterns],
            "reasons": self.reasons,
            "requires_confirmation": self.requires_confirmation,
            "metadata": self.metadata,
        }


class RequestClassifier:
    """Classifies user requests by risk level.

    The classifier analyzes user text input to detect potentially harmful
    intents before any tools are executed. This provides a first line of
    defense against malicious or dangerous requests.

    Usage:
        classifier = RequestClassifier()
        decision = classifier.classify("delete all files on the server")

        if not decision.allowed:
            print(f"Request blocked: {decision.reasons}")
        elif decision.requires_confirmation:
            # Ask user for confirmation
            pass
    """

    # Default risk patterns for request classification
    DEFAULT_PATTERNS = [
        # Critical risk - System destruction
        RiskPattern(
            id="req-destroy-system",
            category=RiskCategory.SYSTEM_DESTRUCTION,
            risk_level=RiskLevel.CRITICAL,
            patterns=[
                r"(?:delete|remove|wipe|destroy|erase).*(?:all|everything|entire|whole)",
                r"(?:format|wipe).*(?:disk|drive|system|server)",
                r"rm\s+-rf\s+/(?:\s|$)",
                r"drop\s+(?:database|table|schema)",
            ],
            keywords=["wipe disk", "format drive", "destroy system", "delete everything"],
            description="Requests that could destroy system or data",
            action="block",
        ),

        # Critical risk - Data exfiltration
        RiskPattern(
            id="req-exfiltrate-data",
            category=RiskCategory.DATA_EXFILTRATION,
            risk_level=RiskLevel.CRITICAL,
            patterns=[
                r"(?:send|upload|transfer|exfil).*(?:all|entire|whole).*(?:data|database|files)",
                r"(?:copy|steal|extract).*(?:credentials|passwords|keys|secrets)",
                r"base64.*\b(?:send|upload|transfer)\b",
            ],
            keywords=["exfiltrate", "steal data", "upload all", "send database"],
            description="Requests to exfiltrate data externally",
            action="block",
        ),

        # Critical risk - Credential theft
        RiskPattern(
            id="req-access-credentials",
            category=RiskCategory.CREDENTIAL_ACCESS,
            risk_level=RiskLevel.CRITICAL,
            patterns=[
                r"(?:read|show|display|get|extract).*(?:password|secret|api.?key|token|credential)",
                r"(?:ssh|private).*(?:key|pem)",
                r"\.env(?:\s|$|\.json|\.yaml)",
                r"(?:aws|gcp|azure).*(?:credentials|secret|key)",
            ],
            keywords=["show password", "read credentials", "get api key", "access tokens"],
            description="Requests to access credentials or secrets",
            action="block",
        ),

        # High risk - Security bypass
        RiskPattern(
            id="req-bypass-security",
            category=RiskCategory.SECURITY_BYPASS,
            risk_level=RiskLevel.HIGH,
            patterns=[
                r"(?:disable|bypass|turn.?off|deactivate).*(?:security|firewall|antivirus|protection)",
                r"(?:ignore|skip).*(?:policy|policies|check|validation)",
                r"sudo(?:\s+sudo|\s+-i|\s+-s)",
            ],
            keywords=["disable security", "bypass policy", "ignore safety", "turn off protection"],
            description="Requests to bypass security measures",
            action="confirm",
            requires_confirmation=True,
        ),

        # High risk - Privilege escalation
        RiskPattern(
            id="req-privilege-escalation",
            category=RiskCategory.PRIVILEGE_ESCALATION,
            risk_level=RiskLevel.HIGH,
            patterns=[
                r"(?:become|switch.?to|run.?as).*(?:root|admin|superuser)",
                r"sudo\s+su(?:\s|$)",
                r"chmod\s+(?:4755|4777|u\+s)",
            ],
            keywords=["become root", "switch to admin", "elevate privileges"],
            description="Requests for privilege escalation",
            action="confirm",
            requires_confirmation=True,
        ),

        # High risk - Network attacks
        RiskPattern(
            id="req-network-attack",
            category=RiskCategory.NETWORK_ATTACK,
            risk_level=RiskLevel.HIGH,
            patterns=[
                r"(?:scan|port.?scan|nmap|masscan)",
                r"(?:exploit|attack|hack|penetrate)",
                r"(?:ddos|dos)\s+attack",
                r"(?:brute.?force|dictionary.?attack)",
            ],
            keywords=["port scan", "network attack", "exploit vulnerability", "hack into"],
            description="Requests for network attacks or reconnaissance",
            action="confirm",
            requires_confirmation=True,
        ),

        # High risk - Arbitrary execution
        RiskPattern(
            id="req-arbitrary-execution",
            category=RiskCategory.ARBITRARY_EXECUTION,
            risk_level=RiskLevel.HIGH,
            patterns=[
                r"(?:curl|wget|fetch)\s+[^|]*\|\s*(?:sh|bash|python|node)",
                r"eval\s*\(",
                r"exec\s*\(",
                r"(?:run|execute).*(?:script|code|binary).*(?:from|url|internet|remote)",
            ],
            keywords=["pipe to bash", "execute from url", "run remote script"],
            description="Requests to execute arbitrary code from untrusted sources",
            action="confirm",
            requires_confirmation=True,
        ),

        # Medium risk - Sensitive file access
        RiskPattern(
            id="req-sensitive-access",
            category=RiskCategory.SENSITIVE_ACCESS,
            risk_level=RiskLevel.MEDIUM,
            patterns=[
                r"(?:read|access|view|open).*(?:\/etc\/|\/var\/|\/root\/)",
                r"\.(?:pem|key|crt|p12|pfx)(?:\s|$)",
                r"(?:\/\.ssh\/|\/\.gnupg\/)",
            ],
            keywords=["access /etc", "read /root", "open ssh folder"],
            description="Requests to access sensitive system files",
            action="log_only",
        ),

        # Medium risk - Unsafe operations
        RiskPattern(
            id="req-unsafe-operation",
            category=RiskCategory.UNSAFE_OPERATION,
            risk_level=RiskLevel.MEDIUM,
            patterns=[
                r"(?:force|skip|ignore).*(?:error|warning|check|validation)",
                r"(?:delete|remove).*(?:\/|\.\.\/|\~)",
                r"(?:truncate|overwrite).*(?:file|database|table)",
            ],
            keywords=["force delete", "skip validation", "ignore errors"],
            description="Requests for potentially unsafe operations",
            action="log_only",
        ),
    ]

    def __init__(
        self,
        patterns: Optional[List[RiskPattern]] = None,
        audit_log_path: Optional[Path] = None,
        on_confirm: Optional[Callable[[str, RequestDecision], bool]] = None,
        high_risk_block: bool = True,
    ):
        """Initialize the request classifier.

        Args:
            patterns: Custom risk patterns (default: DEFAULT_PATTERNS)
            audit_log_path: Path to write audit logs
            on_confirm: Callback for confirmation requests (returns True to proceed)
            high_risk_block: If True, block HIGH and CRITICAL risk; if False, just log
        """
        self.patterns = patterns if patterns is not None else self.DEFAULT_PATTERNS.copy()
        self.audit_log_path = audit_log_path
        self.on_confirm = on_confirm
        self.high_risk_block = high_risk_block
        self._classification_hooks: List[Callable[[str, RequestDecision], None]] = []

    def add_classification_hook(self, hook: Callable[[str, RequestDecision], None]) -> None:
        """Add a hook to be called after every classification."""
        self._classification_hooks.append(hook)

    def classify(self, request_text: str, context: Optional[Dict[str, Any]] = None) -> RequestDecision:
        """Classify a user request by risk level.

        Args:
            request_text: The user's request text to classify
            context: Optional additional context (user, session, etc.)

        Returns:
            RequestDecision with risk level and whether to allow/gate
        """
        matched_patterns: List[RiskPattern] = []
        reasons: List[str] = []
        highest_risk = RiskLevel.LOW

        # Find all matching patterns
        for pattern in self.patterns:
            if pattern.matches(request_text):
                matched_patterns.append(pattern)
                reasons.append(f"{pattern.description} (category: {pattern.category.value})")

                # Track highest risk level
                if self._risk_level_value(pattern.risk_level) > self._risk_level_value(highest_risk):
                    highest_risk = pattern.risk_level

        # Determine if confirmation is needed
        requires_confirmation = any(p.requires_confirmation for p in matched_patterns)

        # Determine if allowed based on risk level
        allowed = self._is_allowed(highest_risk, request_text, matched_patterns)

        # Create decision
        decision = RequestDecision(
            risk_level=highest_risk,
            allowed=allowed,
            matched_patterns=matched_patterns,
            reasons=reasons,
            requires_confirmation=requires_confirmation and allowed,
            metadata={
                "request_text": self._sanitize_request(request_text),
                "timestamp": datetime.utcnow().isoformat(),
                "context": context or {},
            },
        )

        # Log the classification
        self._log_classification(decision)

        # Call hooks
        for hook in self._classification_hooks:
            try:
                hook(request_text, decision)
            except Exception:
                pass

        return decision

    def _risk_level_value(self, level: RiskLevel) -> int:
        """Convert risk level to numeric value for comparison."""
        values = {
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }
        return values.get(level, 0)

    def _is_allowed(self, risk_level: RiskLevel, request_text: str, patterns: List[RiskPattern]) -> bool:
        """Determine if a request should be allowed based on risk level."""
        if not self.high_risk_block:
            return True

        # CRITICAL always blocked
        if risk_level == RiskLevel.CRITICAL:
            return False

        # HIGH requires confirmation if callback available
        if risk_level == RiskLevel.HIGH:
            if self.on_confirm:
                try:
                    decision = RequestDecision(
                        risk_level=risk_level,
                        matched_patterns=patterns,
                        reasons=[p.description for p in patterns],
                        requires_confirmation=True,
                    )
                    return self.on_confirm(request_text, decision)
                except Exception:
                    return False
            return False  # Block if no confirmation handler

        # MEDIUM and LOW are allowed
        return True

    def _sanitize_request(self, text: str) -> str:
        """Sanitize request text for logging."""
        if len(text) > 1000:
            return text[:1000] + "...[truncated]"
        return text

    def _log_classification(self, decision: RequestDecision) -> None:
        """Log classification to audit log if configured."""
        if not self.audit_log_path:
            return

        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            log_entry = {
                "type": "request_classification",
                **decision.to_dict(),
            }
            with self.audit_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=True) + "\n")
        except Exception:
            pass

    def gate_request(self, request_text: str, context: Optional[Dict[str, Any]] = None) -> RequestDecision:
        """Classify and potentially gate a request.

        This is a convenience method that combines classify() with gating logic.

        Args:
            request_text: The user's request text
            context: Optional additional context

        Returns:
            RequestDecision - check .allowed to see if request should proceed
        """
        return self.classify(request_text, context)

    def get_risk_summary(self, request_text: str) -> str:
        """Get a human-readable risk summary for a request.

        Args:
            request_text: The user's request text

        Returns:
            Human-readable summary of detected risks
        """
        decision = self.classify(request_text)

        if not decision.matched_patterns:
            return f"Risk level: {decision.risk_level.value} (no specific risks detected)"

        lines = [f"Risk level: {decision.risk_level.value}"]
        lines.append("Detected risks:")
        for pattern in decision.matched_patterns:
            lines.append(f"  - {pattern.description}")

        return "\n".join(lines)

    @classmethod
    def from_config(cls, config_path: Path, **kwargs) -> "RequestClassifier":
        """Load classifier from configuration file.

        Args:
            config_path: Path to JSON configuration file
            **kwargs: Additional arguments passed to constructor

        Returns:
            Configured RequestClassifier
        """
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)

        patterns = []
        for pattern_data in config.get("patterns", []):
            try:
                patterns.append(RiskPattern.from_dict(pattern_data))
            except (KeyError, ValueError):
                continue

        return cls(
            patterns=patterns if patterns else cls.DEFAULT_PATTERNS,
            audit_log_path=Path(config["audit_log_path"]) if config.get("audit_log_path") else kwargs.get("audit_log_path"),
            high_risk_block=config.get("high_risk_block", kwargs.get("high_risk_block", True)),
            on_confirm=kwargs.get("on_confirm"),
        )
