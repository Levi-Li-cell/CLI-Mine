"""
Task dispatcher for M4-003: Multi-agent roles.

Dispatches tasks to role-specific agents and manages task execution.
"""

import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import AgentRole, AgentTask, AgentTaskStatus, AgentOutput, WorkflowState
from .prompts import (
    render_coder_prompt,
    render_tester_prompt,
    render_reviewer_prompt,
    parse_agent_output,
)


class TaskDispatcher:
    """
    Dispatches tasks to role-specific agents.

    Responsibilities:
    - Create agent tasks with role-appropriate prompts
    - Execute agent commands
    - Parse and return agent outputs
    - Handle timeouts and failures
    """

    def __init__(
        self,
        command_template: str,
        prompt_dir: Path,
        log_dir: Path,
        timeout_seconds: int = 1800,
        agent_executor: Optional[Callable] = None,
    ):
        """
        Initialize the task dispatcher.

        Args:
            command_template: Template for agent command with {prompt_file} placeholder
            prompt_dir: Directory to write prompt files
            log_dir: Directory to write agent output logs
            timeout_seconds: Default timeout for agent execution
            agent_executor: Optional custom executor function (for testing)
        """
        self.command_template = command_template
        self.prompt_dir = Path(prompt_dir)
        self.log_dir = Path(log_dir)
        self.timeout_seconds = timeout_seconds
        self.agent_executor = agent_executor

        # Ensure directories exist
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _generate_task_id(self, role: AgentRole) -> str:
        """Generate a unique task ID."""
        return f"{role.value}_{uuid.uuid4().hex[:8]}"

    def create_task(
        self,
        role: AgentRole,
        feature_id: str,
        description: str = "",
        context: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> AgentTask:
        """
        Create a new agent task.

        Args:
            role: The agent role
            feature_id: Associated feature ID
            description: Task description
            context: Additional context
            timeout_seconds: Task-specific timeout

        Returns:
            Created AgentTask object
        """
        task = AgentTask(
            task_id=self._generate_task_id(role),
            role=role,
            feature_id=feature_id,
            description=description,
            context=context or {},
            timeout_seconds=timeout_seconds or self.timeout_seconds,
        )
        return task

    def render_prompt(
        self,
        task: AgentTask,
        goal_text: str,
        feature: Dict[str, Any],
        previous_outputs: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Render the appropriate prompt for a task.

        Args:
            task: The agent task
            goal_text: Project goal text
            feature: Feature dictionary
            previous_outputs: Previous agent outputs for context

        Returns:
            Rendered prompt string
        """
        previous_outputs = previous_outputs or {}

        if task.role == AgentRole.CODER:
            return render_coder_prompt(goal_text, feature, task.context)
        elif task.role == AgentRole.TESTER:
            coder_output = previous_outputs.get("coder", "")
            return render_tester_prompt(goal_text, feature, coder_output, task.context)
        elif task.role == AgentRole.REVIEWER:
            coder_output = previous_outputs.get("coder", "")
            tester_output = previous_outputs.get("tester", "")
            return render_reviewer_prompt(
                goal_text, feature, coder_output, tester_output, task.context
            )
        else:
            raise ValueError(f"Unknown role: {task.role}")

    def execute_task(
        self,
        task: AgentTask,
        prompt: str,
        cycle_tag: Optional[str] = None,
    ) -> AgentOutput:
        """
        Execute an agent task.

        Args:
            task: The agent task to execute
            prompt: The rendered prompt
            cycle_tag: Optional tag for log file naming

        Returns:
            AgentOutput with execution results
        """
        import json

        # Generate cycle tag if not provided
        if cycle_tag is None:
            cycle_tag = f"{task.role.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Write prompt file
        prompt_file = self.prompt_dir / f"prompt_{cycle_tag}.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Prepare log files
        output_file = self.log_dir / f"agent_output_{cycle_tag}.log"
        error_file = self.log_dir / f"agent_error_{cycle_tag}.log"

        # Mark task as dispatched
        task.mark_dispatched()

        # Execute agent
        returncode = 0
        stdout = ""
        stderr = ""

        try:
            if self.agent_executor:
                # Use custom executor (for testing)
                stdout, stderr, returncode = self.agent_executor(
                    str(prompt_file), task.timeout_seconds
                )
            else:
                # Execute command
                cmd = self.command_template.format(prompt_file=str(prompt_file))
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=task.timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                )
                returncode = result.returncode
                stdout = result.stdout or ""
                stderr = result.stderr or ""

        except subprocess.TimeoutExpired:
            task.mark_timeout()
            return AgentOutput(
                task_id=task.task_id,
                role=task.role,
                feature_id=task.feature_id,
                success=False,
                content="",
                summary="Task timed out",
                issues=["Execution exceeded timeout limit"],
                confidence=0.0,
                metadata={"error": "timeout", "timeout_seconds": task.timeout_seconds},
            )

        except Exception as e:
            task.mark_failed(str(e))
            return AgentOutput(
                task_id=task.task_id,
                role=task.role,
                feature_id=task.feature_id,
                success=False,
                content="",
                summary=f"Execution failed: {e}",
                issues=[str(e)],
                confidence=0.0,
                metadata={"error": str(e)},
            )

        # Write log files
        output_file.write_text(stdout, encoding="utf-8")
        error_file.write_text(stderr, encoding="utf-8")

        # Mark task as completed
        task.mark_completed()

        # Parse output
        output = parse_agent_output(stdout, task.role, task.task_id, task.feature_id)
        output.metadata["returncode"] = returncode
        output.metadata["prompt_file"] = str(prompt_file)
        output.metadata["output_file"] = str(output_file)

        if returncode != 0:
            output.success = False
            output.issues.append(f"Agent returned non-zero exit code: {returncode}")

        return output

    def dispatch_coder(
        self,
        feature_id: str,
        goal_text: str,
        feature: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        cycle_tag: Optional[str] = None,
    ) -> Tuple[AgentTask, AgentOutput]:
        """
        Dispatch a task to the coder agent.

        Args:
            feature_id: Feature ID
            goal_text: Project goal text
            feature: Feature dictionary
            context: Additional context
            cycle_tag: Optional tag for log files

        Returns:
            Tuple of (AgentTask, AgentOutput)
        """
        task = self.create_task(AgentRole.CODER, feature_id, context=context)
        prompt = self.render_prompt(task, goal_text, feature)
        output = self.execute_task(task, prompt, cycle_tag)
        return task, output

    def dispatch_tester(
        self,
        feature_id: str,
        goal_text: str,
        feature: Dict[str, Any],
        coder_output: str,
        context: Optional[Dict[str, Any]] = None,
        cycle_tag: Optional[str] = None,
    ) -> Tuple[AgentTask, AgentOutput]:
        """
        Dispatch a task to the tester agent.

        Args:
            feature_id: Feature ID
            goal_text: Project goal text
            feature: Feature dictionary
            coder_output: Output from the coder agent
            context: Additional context
            cycle_tag: Optional tag for log files

        Returns:
            Tuple of (AgentTask, AgentOutput)
        """
        task = self.create_task(AgentRole.TESTER, feature_id, context=context)
        prompt = self.render_prompt(
            task, goal_text, feature, previous_outputs={"coder": coder_output}
        )
        output = self.execute_task(task, prompt, cycle_tag)
        return task, output

    def dispatch_reviewer(
        self,
        feature_id: str,
        goal_text: str,
        feature: Dict[str, Any],
        coder_output: str,
        tester_output: str,
        context: Optional[Dict[str, Any]] = None,
        cycle_tag: Optional[str] = None,
    ) -> Tuple[AgentTask, AgentOutput]:
        """
        Dispatch a task to the reviewer agent.

        Args:
            feature_id: Feature ID
            goal_text: Project goal text
            feature: Feature dictionary
            coder_output: Output from the coder agent
            tester_output: Output from the tester agent
            context: Additional context
            cycle_tag: Optional tag for log files

        Returns:
            Tuple of (AgentTask, AgentOutput)
        """
        task = self.create_task(AgentRole.REVIEWER, feature_id, context=context)
        prompt = self.render_prompt(
            task,
            goal_text,
            feature,
            previous_outputs={"coder": coder_output, "tester": tester_output},
        )
        output = self.execute_task(task, prompt, cycle_tag)
        return task, output

    def dispatch(
        self,
        role: AgentRole,
        feature_id: str,
        goal_text: str,
        feature: Dict[str, Any],
        previous_outputs: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None,
        cycle_tag: Optional[str] = None,
    ) -> Tuple[AgentTask, AgentOutput]:
        """
        Generic dispatch method for any role.

        Args:
            role: The agent role
            feature_id: Feature ID
            goal_text: Project goal text
            feature: Feature dictionary
            previous_outputs: Previous agent outputs (for tester/reviewer)
            context: Additional context
            cycle_tag: Optional tag for log files

        Returns:
            Tuple of (AgentTask, AgentOutput)
        """
        previous_outputs = previous_outputs or {}

        if role == AgentRole.CODER:
            return self.dispatch_coder(
                feature_id, goal_text, feature, context, cycle_tag
            )
        elif role == AgentRole.TESTER:
            return self.dispatch_tester(
                feature_id,
                goal_text,
                feature,
                previous_outputs.get("coder", ""),
                context,
                cycle_tag,
            )
        elif role == AgentRole.REVIEWER:
            return self.dispatch_reviewer(
                feature_id,
                goal_text,
                feature,
                previous_outputs.get("coder", ""),
                previous_outputs.get("tester", ""),
                context,
                cycle_tag,
            )
        else:
            raise ValueError(f"Unknown role: {role}")


def create_dispatcher(
    command_template: str,
    root_dir: Path,
    timeout_seconds: int = 1800,
    agent_executor: Optional[Callable] = None,
) -> TaskDispatcher:
    """
    Create a TaskDispatcher with standard directories.

    Args:
        command_template: Template for agent command
        root_dir: Project root directory
        timeout_seconds: Default timeout
        agent_executor: Optional custom executor

    Returns:
        Configured TaskDispatcher
    """
    return TaskDispatcher(
        command_template=command_template,
        prompt_dir=root_dir / ".agent" / "prompts",
        log_dir=root_dir / ".agent" / "logs",
        timeout_seconds=timeout_seconds,
        agent_executor=agent_executor,
    )
