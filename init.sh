#!/bin/bash
# init.sh - Initialize and verify the Claude-like AI Agent development environment
# This script performs environment setup and smoke checks for the harness.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Claude-like AI Agent Environment Initialization ==="
echo "Working directory: $(pwd)"
echo ""

# 1. Check Python availability
echo "[1/5] Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "ERROR: Python not found. Please install Python 3.8+"
    exit 1
fi
echo "Python found: $($PYTHON_CMD --version)"

# 2. Check Git availability
echo ""
echo "[2/5] Checking Git..."
if ! command -v git &> /dev/null; then
    echo "ERROR: Git not found. Please install Git."
    exit 1
fi
echo "Git found: $(git --version)"

# 3. Verify required files exist
echo ""
echo "[3/5] Verifying required files..."
REQUIRED_FILES=("harness.py" "config.json" "project_goal.md" "feature_list.json" "claude-progress.txt")
MISSING_FILES=()
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        MISSING_FILES+=("$f")
    fi
done
if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    echo "WARNING: Missing required files: ${MISSING_FILES[*]}"
    echo "Some files may be created by the initializer agent."
else
    echo "All required files present."
fi

# 4. Verify directory structure
echo ""
echo "[4/5] Verifying directory structure..."
mkdir -p .agent/runtime .agent/prompts .agent/logs
echo "Runtime directories ready: .agent/runtime, .agent/prompts, .agent/logs"

# 5. Smoke test - verify harness.py can be loaded
echo ""
echo "[5/5] Running smoke test..."
if $PYTHON_CMD -c "import harness; print('harness.py loaded successfully')" 2>/dev/null; then
    echo "Smoke test PASSED: harness.py loads correctly"
else
    echo "Smoke test WARNING: harness.py may have import issues (this is expected if dependencies are not yet installed)"
fi

echo ""
echo "=== Initialization Complete ==="
echo ""
echo "Next steps:"
echo "  1. Run 'python harness.py --bootstrap' to initialize the project"
echo "  2. Run 'python harness.py --run-forever' for continuous development"
echo "  3. Run 'python harness.py --cycles 1' for a single coding cycle"
echo ""
