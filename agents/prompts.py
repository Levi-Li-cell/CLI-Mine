"""
Role-specific prompt templates for M4-003: Multi-agent roles.

Provides prompt templates for coder, tester, and reviewer agents.
"""

from typing import Any, Dict, Optional

from .models import AgentRole


# Base prompt template shared by all roles
BASE_PROMPT = """You are the {role_name} agent in a multi-agent development system.

You must make incremental progress while keeping the repository in a clean, handoff-ready state.

## ReAct Loop (Reason-Act-Observe)

For every action you take, follow this explicit structure:

### THINK (Reason)
Before using any tool or making changes, write a brief reasoning block:
```
## Think
- Current state: [what you know about the current situation]
- Goal: [what you're trying to accomplish]
- Plan: [which tool/action and why]
```

### ACT (Execute)
Execute the tool or action. Use tools to gather facts from the environment rather than guessing.

### OBSERVE (Review)
After each tool call, write an observation block:
```
## Observe
- Result: [summary of tool output]
- Analysis: [what this means for the task]
- Next: [what to do next - continue, adjust plan, or conclude]
```

Continue the Think-Act-Observe loop until your task is complete.

{role_specific_instructions}

## Session startup checklist

1. Confirm working directory.
2. Read `claude-progress.txt` for recent context.
3. Read the feature details and understand requirements.
4. Review any previous agent outputs provided in context.
5. Perform baseline verification before making changes.

## Work policy

- Focus on your specific role: {role_name}
- Make minimal, coherent changes within your scope
- Document your findings and decisions clearly
- If blocked, document exact blocker and leave reproducible notes

## Final Answer

At the end of your session, emit a final summary:
```
## Final Answer
- Role: {role_name}
- Status: [COMPLETE | BLOCKED | PARTIAL]
- Summary: [what was accomplished]
- Files Modified: [list of files modified, if any]
- Files Created: [list of files created, if any]
- Issues Found: [list of issues, if any]
- Suggestions: [list of suggestions, if any]
- Confidence: [0.0 to 1.0]
```
"""

# Coder-specific instructions
CODER_INSTRUCTIONS = """
## Role: Coder

You are responsible for implementing the feature according to the specifications.

### Your responsibilities:
1. Read and understand the feature requirements
2. Implement the code changes required
3. Ensure code follows project conventions
4. Write clean, maintainable code
5. Consider edge cases and error handling

### Guidelines:
- Start by reading existing code to understand patterns
- Make minimal changes that accomplish the goal
- Follow existing code style and conventions
- Add appropriate error handling
- Consider backwards compatibility
- Do NOT write tests (that's the tester's job)
- Do NOT review your own code (that's the reviewer's job)

### Output format:
When you complete your implementation, provide:
1. A summary of changes made
2. List of files modified/created
3. Any assumptions or decisions made
4. Any areas that need attention from tester/reviewer
"""

# Tester-specific instructions
TESTER_INSTRUCTIONS = """
## Role: Tester

You are responsible for validating the implementation through testing.

### Your responsibilities:
1. Review the coder's implementation
2. Write comprehensive tests for the feature
3. Run existing tests to ensure no regressions
4. Report any bugs or issues found
5. Verify the implementation meets requirements

### Guidelines:
- Write tests that cover the feature requirements
- Test edge cases and error conditions
- Run tests to verify they pass
- If tests fail, document the failure clearly
- Do NOT fix bugs yourself - report them for the coder
- Focus on test quality over quantity

### Test types to consider:
- Unit tests for individual functions
- Integration tests for component interactions
- Edge case tests for boundary conditions
- Error handling tests

### Output format:
When you complete your testing, provide:
1. Summary of tests written/run
2. Test results (pass/fail counts)
3. List of any bugs or issues found
4. Suggestions for improvement
5. Confidence level in the implementation
"""

# Reviewer-specific instructions
REVIEWER_INSTRUCTIONS = """
## Role: Reviewer

You are responsible for reviewing code quality and resolving conflicts between agents.

### Your responsibilities:
1. Review the coder's implementation for quality
2. Review the tester's findings
3. Resolve any conflicts between coder and tester
4. Make final approval/rejection decision
5. Provide clear feedback for revisions

### Review criteria:
- Code correctness and completeness
- Code style and conventions
- Error handling and edge cases
- Test coverage adequacy
- Performance considerations
- Security considerations
- Documentation quality

### Conflict resolution:
When coder and tester disagree:
1. Analyze both perspectives
2. Consider project requirements
3. Make a reasoned decision
4. Document your rationale

### Guidelines:
- Be constructive in feedback
- Prioritize issues by severity
- Provide actionable suggestions
- Consider maintainability
- Do NOT rewrite code yourself - guide revisions

### Output format:
When you complete your review, provide:
1. Overall assessment (approve/revise/reject)
2. List of approved files
3. List of files needing revision with specific issues
4. Required actions before approval
5. Review notes and recommendations
"""


def get_role_name(role: AgentRole) -> str:
    """Get human-readable role name."""
    names = {
        AgentRole.CODER: "Coder",
        AgentRole.TESTER: "Tester",
        AgentRole.REVIEWER: "Reviewer",
    }
    return names.get(role, role.value.capitalize())


def get_role_instructions(role: AgentRole) -> str:
    """Get role-specific instructions."""
    instructions = {
        AgentRole.CODER: CODER_INSTRUCTIONS,
        AgentRole.TESTER: TESTER_INSTRUCTIONS,
        AgentRole.REVIEWER: REVIEWER_INSTRUCTIONS,
    }
    return instructions.get(role, "")


def render_role_prompt(
    role: AgentRole,
    goal_text: str,
    feature: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    previous_outputs: Optional[Dict[str, str]] = None,
) -> str:
    """
    Render a complete prompt for a specific agent role.

    Args:
        role: The agent role
        goal_text: Project goal text
        feature: Feature dictionary from feature_list.json
        context: Additional context for the task
        previous_outputs: Outputs from previous agents (for tester/reviewer)

    Returns:
        Rendered prompt string
    """
    import json

    role_name = get_role_name(role)
    role_instructions = get_role_instructions(role)

    # Build base prompt
    prompt = BASE_PROMPT.format(
        role_name=role_name,
        role_specific_instructions=role_instructions,
    )

    # Add harness context
    prompt += f"""
## Harness context

### Project Goal
{goal_text.strip()}

### Feature to implement
```json
{json.dumps(feature, indent=2, ensure_ascii=True)}
```
"""

    # Add context if provided
    if context:
        prompt += f"""
### Task Context
{json.dumps(context, indent=2, ensure_ascii=True)}
"""

    # Add previous outputs for tester and reviewer
    if previous_outputs:
        prompt += "\n### Previous Agent Outputs\n\n"

        if role == AgentRole.TESTER and "coder" in previous_outputs:
            prompt += f"""
#### Coder's Implementation
{previous_outputs["coder"]}

"""

        elif role == AgentRole.REVIEWER:
            if "coder" in previous_outputs:
                prompt += f"""
#### Coder's Implementation
{previous_outputs["coder"]}

"""
            if "tester" in previous_outputs:
                prompt += f"""
#### Tester's Findings
{previous_outputs["tester"]}

"""

    return prompt


def render_coder_prompt(
    goal_text: str,
    feature: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a prompt for the coder agent."""
    return render_role_prompt(AgentRole.CODER, goal_text, feature, context)


def render_tester_prompt(
    goal_text: str,
    feature: Dict[str, Any],
    coder_output: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a prompt for the tester agent."""
    return render_role_prompt(
        AgentRole.TESTER,
        goal_text,
        feature,
        context,
        previous_outputs={"coder": coder_output},
    )


def render_reviewer_prompt(
    goal_text: str,
    feature: Dict[str, Any],
    coder_output: str,
    tester_output: str,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a prompt for the reviewer agent."""
    return render_role_prompt(
        AgentRole.REVIEWER,
        goal_text,
        feature,
        context,
        previous_outputs={"coder": coder_output, "tester": tester_output},
    )


# Convenience functions for extracting structured data from agent outputs
def extract_final_answer(text: str) -> Dict[str, Any]:
    """
    Extract structured final answer from agent output.

    Args:
        text: Agent output text

    Returns:
        Dictionary with extracted fields
    """
    import re

    result = {
        "role": None,
        "status": "UNKNOWN",
        "summary": "",
        "files_modified": [],
        "files_created": [],
        "issues_found": [],
        "suggestions": [],
        "confidence": 0.5,
    }

    # Match ## Final Answer block
    pattern = re.compile(
        r"## Final Answer\s*\n(.*?)(?=\n## |\Z)",
        re.DOTALL | re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return result

    answer_block = match.group(1)

    # Extract fields
    patterns = {
        "role": r"-?\s*Role:\s*(.+?)(?:\n|$)",
        "status": r"-?\s*Status:\s*(\w+)",
        "summary": r"-?\s*Summary:\s*(.+?)(?=\n-|\n\n|\Z)",
        "files_modified": r"-?\s*Files Modified:\s*\[(.*?)\]",
        "files_created": r"-?\s*Files Created:\s*\[(.*?)\]",
        "issues_found": r"-?\s*Issues Found:\s*\[(.*?)\]",
        "suggestions": r"-?\s*Suggestions:\s*\[(.*?)\]",
        "confidence": r"-?\s*Confidence:\s*([\d.]+)",
    }

    for field, pattern in patterns.items():
        m = re.search(pattern, answer_block, re.IGNORECASE | re.DOTALL)
        if m:
            value = m.group(1).strip()
            if field in ("files_modified", "files_created", "issues_found", "suggestions"):
                # Parse list items
                items = [item.strip().strip("'\"") for item in value.split(",") if item.strip()]
                result[field] = items
            elif field == "confidence":
                try:
                    result[field] = float(value)
                except ValueError:
                    pass
            else:
                result[field] = value

    return result


def parse_agent_output(text: str, role: AgentRole, task_id: str, feature_id: str) -> "AgentOutput":
    """
    Parse agent output text into an AgentOutput object.

    Args:
        text: Agent output text
        role: The agent role
        task_id: Task ID
        feature_id: Feature ID

    Returns:
        AgentOutput object
    """
    from .models import AgentOutput

    answer = extract_final_answer(text)

    output = AgentOutput(
        task_id=task_id,
        role=role,
        feature_id=feature_id,
        success=answer["status"] in ("COMPLETE", "APPROVE"),
        content=text,
        summary=answer["summary"],
        issues=answer["issues_found"],
        suggestions=answer["suggestions"],
        files_modified=answer["files_modified"],
        files_created=answer["files_created"],
        confidence=answer["confidence"],
    )
    output.metadata["parsed_status"] = answer["status"]
    output.metadata["parsed_role"] = answer["role"]
    return output
