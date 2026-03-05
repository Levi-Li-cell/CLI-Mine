"""Multi-agent workflow package for role-based execution."""

from .dispatcher import TaskDispatcher, create_dispatcher
from .models import (
    AgentRole,
    AgentTask,
    AgentTaskStatus,
    AgentOutput,
    Conflict,
    ConflictType,
    AggregatedDecision,
    DecisionType,
    WorkflowState,
)
from .orchestrator import MultiAgentOrchestrator, create_orchestrator

__all__ = [
    "TaskDispatcher",
    "create_dispatcher",
    "AgentRole",
    "AgentTask",
    "AgentTaskStatus",
    "AgentOutput",
    "Conflict",
    "ConflictType",
    "AggregatedDecision",
    "DecisionType",
    "WorkflowState",
    "MultiAgentOrchestrator",
    "create_orchestrator",
]
