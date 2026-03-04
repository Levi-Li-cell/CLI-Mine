"""
Core policy definitions for Constitutional safety system.

Defines machine-readable policy rules and constitution structure.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern
import re


class RiskLevel(Enum):
    """Risk classification levels for actions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyAction(Enum):
    """Action to take when a policy rule matches."""
    ALLOW = "allow"           # Explicitly allow the action
    BLOCK = "block"           # Block and return error
    CONFIRM = "confirm"       # Require user confirmation
    DEGRADE = "degrade"       # Execute with reduced capability
    LOG_ONLY = "log_only"     # Allow but log the action


@dataclass
class PolicyRule:
    """A single policy rule that can be evaluated against actions.

    Attributes:
        id: Unique identifier for this rule
        description: Human-readable description
        risk_level: Classification of risk level
        action: What action to take when rule matches
        tool_name: Tool this rule applies to (None = all tools)
        pattern: Regex pattern to match against action parameters
        pattern_fields: Which fields to match the pattern against
        alternative: Suggested safe alternative (for BLOCK/DEGRADE)
        enabled: Whether this rule is active
        priority: Higher priority rules are checked first
    """
    id: str
    description: str
    risk_level: RiskLevel
    action: PolicyAction
    tool_name: Optional[str] = None
    pattern: Optional[str] = None
    pattern_fields: List[str] = field(default_factory=lambda: ["command", "path", "url"])
    alternative: Optional[str] = None
    enabled: bool = True
    priority: int = 100

    _compiled_pattern: Optional[Pattern] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.pattern and not self._compiled_pattern:
            try:
                self._compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
            except re.error:
                self._compiled_pattern = None

    def matches(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Check if this rule matches the given tool action.

        Args:
            tool_name: Name of the tool being invoked
            arguments: Arguments passed to the tool

        Returns:
            True if the rule matches and should be applied
        """
        if not self.enabled:
            return False

        # Check if tool matches (None means all tools)
        if self.tool_name and self.tool_name != tool_name:
            return False

        # If no pattern, rule matches based on tool only
        if not self.pattern or not self._compiled_pattern:
            return self.tool_name == tool_name

        # Check pattern against specified fields
        for field_name in self.pattern_fields:
            value = arguments.get(field_name)
            if isinstance(value, str) and self._compiled_pattern.search(value):
                return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize rule to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "action": self.action.value,
            "tool_name": self.tool_name,
            "pattern": self.pattern,
            "pattern_fields": self.pattern_fields,
            "alternative": self.alternative,
            "enabled": self.enabled,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyRule":
        """Deserialize rule from dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            risk_level=RiskLevel(data.get("risk_level", "medium")),
            action=PolicyAction(data.get("action", "block")),
            tool_name=data.get("tool_name"),
            pattern=data.get("pattern"),
            pattern_fields=data.get("pattern_fields", ["command", "path", "url"]),
            alternative=data.get("alternative"),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
        )


@dataclass
class Constitution:
    """A collection of policy rules that govern agent behavior.

    The Constitution represents the "behavioral contract" that the agent
    must follow. It is loaded from a machine-readable file and can be
    updated without code changes.

    Attributes:
        name: Human-readable name for this constitution
        version: Version string
        rules: List of policy rules
        default_action: Action when no rules match (default: ALLOW)
        high_risk_default: Action for high-risk actions with no specific rule
    """
    name: str = "Default Constitution"
    version: str = "1.0.0"
    rules: List[PolicyRule] = field(default_factory=list)
    default_action: PolicyAction = PolicyAction.ALLOW
    high_risk_default: PolicyAction = PolicyAction.LOG_ONLY

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a rule to the constitution."""
        self.rules.append(rule)
        # Keep rules sorted by priority (highest first)
        self.rules.sort(key=lambda r: -r.priority)

    def get_matching_rules(self, tool_name: str, arguments: Dict[str, Any]) -> List[PolicyRule]:
        """Get all rules that match the given action, sorted by priority."""
        return [r for r in self.rules if r.matches(tool_name, arguments)]

    def get_highest_priority_match(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[PolicyRule]:
        """Get the highest priority matching rule."""
        matches = self.get_matching_rules(tool_name, arguments)
        return matches[0] if matches else None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize constitution to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "default_action": self.default_action.value,
            "high_risk_default": self.high_risk_default.value,
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Constitution":
        """Deserialize constitution from dictionary."""
        constitution = cls(
            name=data.get("name", "Constitution"),
            version=data.get("version", "1.0.0"),
            default_action=PolicyAction(data.get("default_action", "allow")),
            high_risk_default=PolicyAction(data.get("high_risk_default", "log_only")),
        )
        for rule_data in data.get("rules", []):
            try:
                rule = PolicyRule.from_dict(rule_data)
                constitution.rules.append(rule)
            except (KeyError, ValueError) as e:
                # Skip malformed rules but continue loading
                continue
        # Sort by priority
        constitution.rules.sort(key=lambda r: -r.priority)
        return constitution

    @classmethod
    def from_yaml(cls, path: Path) -> "Constitution":
        """Load constitution from YAML file.

        Falls back to JSON parsing if PyYAML is not available.
        """
        import json

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Constitution file not found: {path}")

        content = path.read_text(encoding="utf-8")

        # Try YAML first, fall back to JSON
        try:
            import yaml
            data = yaml.safe_load(content)
        except ImportError:
            # PyYAML not available, try JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Simple YAML-like parser for basic files
                data = cls._parse_simple_yaml(content)

        if not isinstance(data, dict):
            raise ValueError(f"Constitution file must contain a dictionary, got {type(data)}")

        return cls.from_dict(data)

    @staticmethod
    def _parse_simple_yaml(content: str) -> Dict[str, Any]:
        """Simple YAML parser for basic constitution files.

        Handles the subset of YAML used by constitution files.
        This is a fallback when PyYAML is not available.
        """
        import json

        # Try to parse as JSON first (common case)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Simple YAML parsing for the constitution format
        result = {"name": "", "version": "1.0.0", "rules": []}
        current_rule = None
        in_rules = False

        for line in content.split("\n"):
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue

            # Check for top-level keys
            if stripped.startswith("name:"):
                result["name"] = stripped[5:].strip().strip('"').strip("'")
            elif stripped.startswith("version:"):
                result["version"] = stripped[8:].strip().strip('"').strip("'")
            elif stripped.startswith("default_action:"):
                result["default_action"] = stripped[15:].strip().strip('"').strip("'")
            elif stripped.startswith("rules:"):
                in_rules = True
            elif in_rules and stripped.startswith("- id:"):
                if current_rule:
                    result["rules"].append(current_rule)
                current_rule = {"id": stripped[5:].strip().strip('"').strip("'")}
            elif in_rules and current_rule and ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip().strip("-")
                value = value.strip().strip('"').strip("'")
                if key == "pattern_fields":
                    # Handle list format
                    current_rule[key] = [v.strip().strip('"').strip("'") for v in value.split(",")]
                else:
                    current_rule[key] = value

        if current_rule:
            result["rules"].append(current_rule)

        return result
