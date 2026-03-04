"""
Sandbox and allowlist system for destructive shell commands.

This module implements a layered security approach:
1. Command categorization (read-only, write, network, destructive, etc.)
2. Allowlist-based approval for command categories
3. Forbidden pattern blocking for dangerous operations
4. Clear denial reasons with suggested alternatives

Usage:
    from safety.sandbox import ShellSandbox, SandboxMode

    # Create sandbox with default allowlist
    sandbox = ShellSandbox()

    # Check if command is allowed
    decision = sandbox.evaluate("rm -rf /project/build")
    if decision.allowed:
        # Execute command
        pass
    else:
        print(f"Blocked: {decision.reason}")
        if decision.alternative:
            print(f"Alternative: {decision.alternative}")

    # Use strict mode (only allowlisted commands)
    strict_sandbox = ShellSandbox(mode=SandboxMode.STRICT)
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import json
import re
import shlex


class CommandCategory(Enum):
    """Categories for shell commands based on their risk level."""
    READ_ONLY = "read_only"           # Safe: ls, cat, head, grep, find (no exec)
    FILE_WRITE = "file_write"         # Moderate: touch, mkdir, cp, mv (within sandbox)
    FILE_DELETE = "file_delete"       # Risky: rm, rmdir
    SYSTEM_INFO = "system_info"       # Safe: pwd, whoami, uname, date
    NETWORK = "network"               # Moderate: curl, wget, ping, ssh
    PACKAGE_MGMT = "package_mgmt"     # Risky: apt, yum, npm, pip
    PROCESS_MGMT = "process_mgmt"     # Moderate: ps, top, kill
    DESTRUCTIVE = "destructive"       # Dangerous: rm -rf /, mkfs, dd
    PRIVILEGED = "privileged"         # Dangerous: sudo, su, chmod 777
    UNKNOWN = "unknown"               # Unclassified - treat with caution


class SandboxMode(Enum):
    """Operating mode for the sandbox."""
    PERMISSIVE = "permissive"   # Allow unless explicitly blocked
    MODERATE = "moderate"       # Block destructive/privileged, allow others
    STRICT = "strict"           # Only allow explicitly allowlisted commands


@dataclass
class SandboxDecision:
    """Result of evaluating a command against sandbox rules.

    Attributes:
        allowed: Whether the command is permitted
        category: The determined command category
        reason: Human-readable explanation
        alternative: Suggested safe alternative (if available)
        matched_forbidden: Forbidden pattern that was matched (if any)
        command_parts: Parsed command components
        metadata: Additional context for logging
    """
    allowed: bool
    category: CommandCategory
    reason: str = ""
    alternative: Optional[str] = None
    matched_forbidden: Optional[str] = None
    command_parts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize decision to dictionary."""
        return {
            "allowed": self.allowed,
            "category": self.category.value,
            "reason": self.reason,
            "alternative": self.alternative,
            "matched_forbidden": self.matched_forbidden,
            "command_parts": self.command_parts,
            "metadata": self.metadata,
        }


@dataclass
class CommandRule:
    """A rule for categorizing and handling a specific command.

    Attributes:
        command: The command name (e.g., 'rm', 'ls')
        category: The category this command belongs to
        safe_flags: Flags that make the command safer (e.g., '-i' for rm)
        dangerous_flags: Flags that make the command more dangerous
        requires_path: Whether the command requires a path argument
        allowed_in_strict: Whether allowed in strict mode
        alternative: Suggested alternative for blocked usage
    """
    command: str
    category: CommandCategory
    safe_flags: Set[str] = field(default_factory=set)
    dangerous_flags: Set[str] = field(default_factory=set)
    requires_path: bool = False
    allowed_in_strict: bool = False
    alternative: Optional[str] = None


# Default command rules database
DEFAULT_COMMAND_RULES: List[CommandRule] = [
    # Read-only commands
    CommandRule("ls", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("cat", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("head", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("tail", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("less", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("more", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("grep", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("find", CommandCategory.READ_ONLY, dangerous_flags={"-exec", "-execdir"}, allowed_in_strict=True),
    CommandRule("wc", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("sort", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("uniq", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("diff", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("tree", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("stat", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("file", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("which", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("whereis", CommandCategory.READ_ONLY, allowed_in_strict=True),
    CommandRule("type", CommandCategory.READ_ONLY, allowed_in_strict=True),

    # System info commands
    CommandRule("pwd", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("whoami", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("uname", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("date", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("echo", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("env", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("printenv", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("hostname", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("uptime", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("df", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("du", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("free", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("id", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),
    CommandRule("groups", CommandCategory.SYSTEM_INFO, allowed_in_strict=True),

    # File write commands
    CommandRule("touch", CommandCategory.FILE_WRITE, allowed_in_strict=True),
    CommandRule("mkdir", CommandCategory.FILE_WRITE, allowed_in_strict=True),
    CommandRule("cp", CommandCategory.FILE_WRITE, allowed_in_strict=True),
    CommandRule("mv", CommandCategory.FILE_WRITE, allowed_in_strict=True),
    CommandRule("ln", CommandCategory.FILE_WRITE),
    CommandRule("chmod", CommandCategory.FILE_WRITE, dangerous_flags={"-R", "777"}),
    CommandRule("chown", CommandCategory.FILE_WRITE, dangerous_flags={"-R"}),
    CommandRule("truncate", CommandCategory.FILE_WRITE),

    # File delete commands
    CommandRule("rm", CommandCategory.FILE_DELETE, dangerous_flags={"-rf", "-r", "-f"}, alternative="Use 'rm -i' for interactive deletion or move to trash first"),
    CommandRule("rmdir", CommandCategory.FILE_DELETE, allowed_in_strict=True),

    # Network commands
    CommandRule("curl", CommandCategory.NETWORK, dangerous_flags={"| sh", "| bash"}),
    CommandRule("wget", CommandCategory.NETWORK, dangerous_flags={"| sh", "| bash"}),
    CommandRule("ping", CommandCategory.NETWORK, allowed_in_strict=True),
    CommandRule("nc", CommandCategory.NETWORK, dangerous_flags={"-e", "-c"}),
    CommandRule("ssh", CommandCategory.NETWORK),
    CommandRule("scp", CommandCategory.NETWORK),
    CommandRule("rsync", CommandCategory.NETWORK),
    CommandRule("telnet", CommandCategory.NETWORK),
    CommandRule("nslookup", CommandCategory.NETWORK, allowed_in_strict=True),
    CommandRule("dig", CommandCategory.NETWORK, allowed_in_strict=True),
    CommandRule("ip", CommandCategory.NETWORK, dangerous_flags={"link set", "addr add", "route add"}),

    # Package management
    CommandRule("apt", CommandCategory.PACKAGE_MGMT),
    CommandRule("apt-get", CommandCategory.PACKAGE_MGMT),
    CommandRule("yum", CommandCategory.PACKAGE_MGMT),
    CommandRule("dnf", CommandCategory.PACKAGE_MGMT),
    CommandRule("pip", CommandCategory.PACKAGE_MGMT),
    CommandRule("pip3", CommandCategory.PACKAGE_MGMT),
    CommandRule("npm", CommandCategory.PACKAGE_MGMT),
    CommandRule("yarn", CommandCategory.PACKAGE_MGMT),
    CommandRule("gem", CommandCategory.PACKAGE_MGMT),
    CommandRule("cargo", CommandCategory.PACKAGE_MGMT),
    CommandRule("go", CommandCategory.PACKAGE_MGMT),

    # Process management
    CommandRule("ps", CommandCategory.PROCESS_MGMT, allowed_in_strict=True),
    CommandRule("top", CommandCategory.PROCESS_MGMT, allowed_in_strict=True),
    CommandRule("htop", CommandCategory.PROCESS_MGMT, allowed_in_strict=True),
    CommandRule("kill", CommandCategory.PROCESS_MGMT),
    CommandRule("killall", CommandCategory.PROCESS_MGMT),
    CommandRule("pkill", CommandCategory.PROCESS_MGMT),
    CommandRule("bg", CommandCategory.PROCESS_MGMT),
    CommandRule("fg", CommandCategory.PROCESS_MGMT),
    CommandRule("jobs", CommandCategory.PROCESS_MGMT, allowed_in_strict=True),
    CommandRule("nice", CommandCategory.PROCESS_MGMT),
    CommandRule("renice", CommandCategory.PROCESS_MGMT),
    CommandRule("nohup", CommandCategory.PROCESS_MGMT),

    # Privileged commands
    CommandRule("sudo", CommandCategory.PRIVILEGED, alternative="Run without sudo if possible, or request explicit approval"),
    CommandRule("su", CommandCategory.PRIVILEGED, alternative="Use sudo for specific commands instead"),
    CommandRule("doas", CommandCategory.PRIVILEGED),
    CommandRule("pkexec", CommandCategory.PRIVILEGED),

    # Destructive commands (always blocked patterns)
    CommandRule("mkfs", CommandCategory.DESTRUCTIVE, alternative="Disk formatting requires explicit human approval"),
    CommandRule("dd", CommandCategory.DESTRUCTIVE, alternative="Direct disk operations require explicit human approval"),
    CommandRule("shred", CommandCategory.DESTRUCTIVE),
    CommandRule("wipefs", CommandCategory.DESTRUCTIVE),
]

# Forbidden patterns that are always blocked
FORBIDDEN_PATTERNS = [
    (r"rm\s+(-[rf]+\s+)*(/\s*$|/\*\s*$|~\s*$)", "Root/home directory deletion"),
    (r"rm\s+(-[rf]+\s+)*/(usr|etc|var|boot|proc|sys)(/|$)", "System directory deletion"),
    (r"mkfs\.?\w*\s+/dev/", "Filesystem creation on device"),
    (r"dd\s+.*of=/dev/", "Direct disk write"),
    (r">\s*/dev/s[d-z]", "Direct disk write"),
    (r":\(\)\s*\{\s*:\|:&\s*\}\s*;:", "Fork bomb"),
    (r"chmod\s+(-R\s+)?777\s+/", "Recursive permission flood on root"),
    (r"chown\s+(-R\s+)?\w+\s+/", "Recursive ownership change on root"),
    (r">(>\s*)?/dev/null\s+2>&1\s*&&\s*rm", "Hidden deletion pattern"),
    (r"(wget|curl)\s+[^|]*\|\s*(ba)?sh", "Remote script execution"),
    (r"eval\s+['\"]", "Eval with quoted string"),
    (r"exec\s+<", "Input redirection with exec"),
    (r"/dev/zero\s*>\s*/dev/", "Device zeroing"),
]


@dataclass
class SandboxConfig:
    """Configuration for sandbox behavior.

    Attributes:
        mode: Operating mode (permissive/moderate/strict)
        allowed_categories: Categories allowed in moderate/strict mode
        forbidden_patterns: Regex patterns that are always blocked
        allowed_directories: Directories where file operations are allowed
        blocked_directories: Directories where operations are always blocked
        allow_package_mgmt: Whether to allow package management commands
        allow_network: Whether to allow network commands
        allow_privileged: Whether to allow sudo/su commands
        audit_log_path: Path for audit logging
    """
    mode: SandboxMode = SandboxMode.MODERATE
    allowed_categories: Set[CommandCategory] = field(default_factory=lambda: {
        CommandCategory.READ_ONLY,
        CommandCategory.SYSTEM_INFO,
        CommandCategory.FILE_WRITE,
        CommandCategory.FILE_DELETE,
    })
    forbidden_patterns: List[tuple] = field(default_factory=lambda: FORBIDDEN_PATTERNS)
    allowed_directories: List[str] = field(default_factory=list)
    blocked_directories: List[str] = field(default_factory=lambda: [
        "/", "/usr", "/etc", "/var", "/boot", "/proc", "/sys", "/dev", "/root"
    ])
    allow_package_mgmt: bool = False
    allow_network: bool = True
    allow_privileged: bool = False
    audit_log_path: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SandboxConfig":
        """Create config from dictionary."""
        mode = SandboxMode(data.get("mode", "moderate"))
        allowed_categories = {
            CommandCategory(c) for c in data.get("allowed_categories", [
                "read_only", "system_info", "file_write", "file_delete"
            ])
        }
        return cls(
            mode=mode,
            allowed_categories=allowed_categories,
            allowed_directories=data.get("allowed_directories", []),
            blocked_directories=data.get("blocked_directories", [
                "/", "/usr", "/etc", "/var", "/boot", "/proc", "/sys", "/dev", "/root"
            ]),
            allow_package_mgmt=data.get("allow_package_mgmt", False),
            allow_network=data.get("allow_network", True),
            allow_privileged=data.get("allow_privileged", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize config to dictionary."""
        return {
            "mode": self.mode.value,
            "allowed_categories": [c.value for c in self.allowed_categories],
            "allowed_directories": self.allowed_directories,
            "blocked_directories": self.blocked_directories,
            "allow_package_mgmt": self.allow_package_mgmt,
            "allow_network": self.allow_network,
            "allow_privileged": self.allow_privileged,
        }


class ShellSandbox:
    """Sandbox for evaluating and filtering shell commands.

    This class provides a layered security model:
    1. Parse command to extract command name and arguments
    2. Check against forbidden patterns (always blocked)
    3. Categorize the command
    4. Check category against allowlist based on mode
    5. Check for dangerous flags within allowed categories
    6. Return decision with clear reason and alternatives

    Usage:
        sandbox = ShellSandbox()
        decision = sandbox.evaluate("rm -rf /project/build")
    """

    def __init__(
        self,
        config: Optional[SandboxConfig] = None,
        custom_rules: Optional[List[CommandRule]] = None,
    ):
        """Initialize the sandbox.

        Args:
            config: Sandbox configuration (uses defaults if not provided)
            custom_rules: Additional command rules to add/override
        """
        self.config = config or SandboxConfig()
        self._rules: Dict[str, CommandRule] = {}

        # Load default rules
        for rule in DEFAULT_COMMAND_RULES:
            self._rules[rule.command] = rule

        # Add/override with custom rules
        if custom_rules:
            for rule in custom_rules:
                self._rules[rule.command] = rule

        # Compile forbidden patterns
        self._compiled_forbidden = [
            (re.compile(p, re.IGNORECASE), reason)
            for p, reason in self.config.forbidden_patterns
        ]

    def _parse_command(self, command: str) -> List[str]:
        """Parse command into parts, handling quotes and escapes."""
        try:
            return shlex.split(command)
        except ValueError:
            # Fallback for malformed commands
            return command.split()

    def _get_command_rule(self, command_parts: List[str]) -> Optional[CommandRule]:
        """Get the rule for a command, handling sudo/doas prefixes.

        If command starts with sudo/su/doas/pkexec, return the privileged rule
        to ensure these commands are categorized as PRIVILEGED.
        """
        if not command_parts:
            return None

        # Handle sudo/su/doas prefix - return privileged rule for the prefix itself
        if command_parts[0] in ("sudo", "su", "doas", "pkexec"):
            return self._rules.get(command_parts[0])

        cmd_name = command_parts[0]
        # Handle path-based commands (e.g., /usr/bin/ls)
        if "/" in cmd_name:
            cmd_name = cmd_name.split("/")[-1]

        return self._rules.get(cmd_name)

    def _check_forbidden_patterns(self, command: str) -> Optional[tuple]:
        """Check if command matches any forbidden pattern."""
        for pattern, reason in self._compiled_forbidden:
            if pattern.search(command):
                return (pattern.pattern, reason)
        return None

    def _check_dangerous_flags(self, command: str, rule: CommandRule) -> Optional[str]:
        """Check if command uses dangerous flags for the given rule."""
        if not rule.dangerous_flags:
            return None

        cmd_lower = command.lower()
        for flag in rule.dangerous_flags:
            if flag.lower() in cmd_lower:
                return flag
        return None

    def _check_blocked_directory(self, command: str) -> Optional[str]:
        """Check if command operates on a blocked directory."""
        for blocked_dir in self.config.blocked_directories:
            # Check for operations on blocked directories
            patterns = [
                rf"\s+{re.escape(blocked_dir)}(/|\s|$)",
                rf"\s+{re.escape(blocked_dir)}$",
            ]
            for pattern in patterns:
                if re.search(pattern, command):
                    return blocked_dir
        return None

    def _get_allowed_categories(self) -> Set[CommandCategory]:
        """Get allowed categories based on mode and config."""
        base_categories = set(self.config.allowed_categories)

        # Adjust based on config flags
        if self.config.allow_package_mgmt:
            base_categories.add(CommandCategory.PACKAGE_MGMT)
        if self.config.allow_network:
            base_categories.add(CommandCategory.NETWORK)
        if self.config.allow_privileged:
            base_categories.add(CommandCategory.PRIVILEGED)

        return base_categories

    def evaluate(self, command: str) -> SandboxDecision:
        """Evaluate a command against sandbox rules.

        Args:
            command: The shell command to evaluate

        Returns:
            SandboxDecision with allowed status, reason, and alternative
        """
        command = command.strip()
        command_parts = self._parse_command(command)

        if not command_parts:
            return SandboxDecision(
                allowed=False,
                category=CommandCategory.UNKNOWN,
                reason="Empty command",
                command_parts=[],
            )

        # Step 1: Check forbidden patterns (always blocked)
        forbidden_match = self._check_forbidden_patterns(command)
        if forbidden_match:
            pattern, reason = forbidden_match
            return SandboxDecision(
                allowed=False,
                category=CommandCategory.DESTRUCTIVE,
                reason=f"Command matches forbidden pattern: {reason}",
                matched_forbidden=pattern,
                command_parts=command_parts,
                alternative="This operation is too dangerous to automate. Please perform manually if needed.",
            )

        # Step 2: Get command rule
        rule = self._get_command_rule(command_parts)

        if not rule:
            # Unknown command - handle based on mode
            if self.config.mode == SandboxMode.STRICT:
                return SandboxDecision(
                    allowed=False,
                    category=CommandCategory.UNKNOWN,
                    reason=f"Unknown command '{command_parts[0]}' is not allowed in strict mode",
                    command_parts=command_parts,
                    alternative="Only explicitly allowlisted commands are permitted in strict mode",
                )
            # Permissive/moderate: allow unknown with caution
            return SandboxDecision(
                allowed=True,
                category=CommandCategory.UNKNOWN,
                reason="Unknown command - allowed with caution",
                command_parts=command_parts,
                metadata={"warning": "Command not in allowlist"},
            )

        category = rule.category

        # Step 3: Check if category is allowed
        allowed_categories = self._get_allowed_categories()

        # Permissive mode: allow all except destructive/privileged
        if self.config.mode == SandboxMode.PERMISSIVE:
            if category in (CommandCategory.DESTRUCTIVE, CommandCategory.PRIVILEGED):
                return SandboxDecision(
                    allowed=False,
                    category=category,
                    reason=f"Command '{command_parts[0]}' is in blocked category: {category.value}",
                    command_parts=command_parts,
                    alternative=rule.alternative,
                )

        # Moderate/Strict mode: check category allowlist
        elif category not in allowed_categories:
            return SandboxDecision(
                allowed=False,
                category=category,
                reason=f"Command '{command_parts[0]}' is in category '{category.value}' which is not allowed in {self.config.mode.value} mode",
                command_parts=command_parts,
                alternative=rule.alternative,
            )

        # Step 4: Check for dangerous flags within allowed category
        dangerous_flag = self._check_dangerous_flags(command, rule)
        if dangerous_flag:
            return SandboxDecision(
                allowed=False,
                category=category,
                reason=f"Command '{command_parts[0]}' uses dangerous flag '{dangerous_flag}'",
                command_parts=command_parts,
                alternative=rule.alternative,
            )

        # Step 5: Check blocked directories for file operations
        if category in (CommandCategory.FILE_WRITE, CommandCategory.FILE_DELETE):
            blocked_dir = self._check_blocked_directory(command)
            if blocked_dir:
                return SandboxDecision(
                    allowed=False,
                    category=category,
                    reason=f"Command operates on blocked directory: {blocked_dir}",
                    command_parts=command_parts,
                    alternative=f"Perform operations within your project directory, not system directories",
                )

        # Step 6: Strict mode - check if command is explicitly allowed
        if self.config.mode == SandboxMode.STRICT and not rule.allowed_in_strict:
            return SandboxDecision(
                allowed=False,
                category=category,
                reason=f"Command '{command_parts[0]}' is not allowed in strict mode",
                command_parts=command_parts,
                alternative=rule.alternative or "Only safe read-only and system info commands are allowed in strict mode",
            )

        # All checks passed
        return SandboxDecision(
            allowed=True,
            category=category,
            reason=f"Command allowed in {self.config.mode.value} mode",
            command_parts=command_parts,
            metadata={"rule_id": rule.command},
        )

    def get_command_info(self, command: str) -> Dict[str, Any]:
        """Get detailed information about a command without blocking.

        Useful for UI hints and debugging.
        """
        command_parts = self._parse_command(command)
        rule = self._get_command_rule(command_parts)
        decision = self.evaluate(command)

        return {
            "command": command,
            "command_parts": command_parts,
            "category": decision.category.value,
            "rule": {
                "command": rule.command if rule else None,
                "category": rule.category.value if rule else None,
                "safe_flags": list(rule.safe_flags) if rule else [],
                "dangerous_flags": list(rule.dangerous_flags) if rule else [],
            } if rule else None,
            "decision": decision.to_dict(),
        }

    def add_rule(self, rule: CommandRule) -> None:
        """Add or update a command rule."""
        self._rules[rule.command] = rule

    def get_allowed_commands(self) -> List[str]:
        """Get list of commands allowed in current mode."""
        allowed = []
        allowed_categories = self._get_allowed_categories()

        for cmd, rule in self._rules.items():
            if rule.category in allowed_categories:
                if self.config.mode != SandboxMode.STRICT or rule.allowed_in_strict:
                    allowed.append(cmd)

        return sorted(allowed)

    def get_blocked_commands(self) -> List[str]:
        """Get list of commands blocked in current mode."""
        blocked = []
        allowed_categories = self._get_allowed_categories()

        for cmd, rule in self._rules.items():
            if rule.category not in allowed_categories:
                blocked.append(cmd)
            elif self.config.mode == SandboxMode.STRICT and not rule.allowed_in_strict:
                blocked.append(cmd)

        return sorted(blocked)


def create_default_sandbox(
    mode: SandboxMode = SandboxMode.MODERATE,
    allowed_dir: Optional[str] = None,
) -> ShellSandbox:
    """Create a sandbox with sensible defaults.

    Args:
        mode: Operating mode
        allowed_dir: Optional directory to restrict operations to

    Returns:
        Configured ShellSandbox instance
    """
    config = SandboxConfig(mode=mode)

    if allowed_dir:
        config.allowed_directories = [allowed_dir]

    return ShellSandbox(config=config)
