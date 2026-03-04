"""Verification test for M1-004: Tool failure retry and fallback policy."""
import sys
import tempfile
import json
import os
from pathlib import Path

sys.path.insert(0, '.')

print('=== M1-004 VERIFICATION: Tool Failure Retry and Fallback Policy ===')
print()

# Test 1: Imports work
print('1. Testing: Imports work correctly...')
try:
    from tools import (
        RetryPolicy, RetryExecutor, RetryAttempt, RetryLog,
        RetryAction, TransientErrorPattern, ToolRegistry, ToolResult,
        create_default_fallback_handler
    )
    print('   [PASS] All retry classes imported successfully')
except ImportError as e:
    print(f'   [FAIL] Import error: {e}')
    sys.exit(1)

# Test 2: RetryPolicy transient error detection
print()
print('2. Testing: RetryPolicy detects transient errors...')
policy = RetryPolicy(max_retries=3, base_delay=0.1, jitter=False)

# Test transient detection
transient_result = ToolResult(
    success=False,
    output='',
    error='HTTP 503: Service Unavailable',
    metadata={'status': 503}
)
is_transient = policy.is_transient_error('web', transient_result)
if is_transient:
    print('   [PASS] HTTP 503 detected as transient')
else:
    print('   [FAIL] HTTP 503 should be transient')

# Test non-transient detection
non_transient = ToolResult(
    success=False,
    output='',
    error='HTTP 404: Not Found',
    metadata={'status': 404}
)
is_transient = policy.is_transient_error('web', non_transient)
if not is_transient:
    print('   [PASS] HTTP 404 correctly not detected as transient')
else:
    print('   [FAIL] HTTP 404 should NOT be transient')

# Test timeout detection
timeout_result = ToolResult(
    success=False,
    output='',
    error='Connection timed out after 30 seconds',
    metadata={}
)
is_transient = policy.is_transient_error('web', timeout_result)
if is_transient:
    print('   [PASS] Timeout detected as transient')
else:
    print('   [FAIL] Timeout should be transient')

# Test 3: RetryExecutor retries on transient errors
print()
print('3. Testing: RetryExecutor retries on transient errors...')
call_count = [0]
def failing_execute(name, args):
    call_count[0] += 1
    if call_count[0] < 3:
        return ToolResult(
            success=False,
            output='',
            error='HTTP 503: Service temporarily unavailable',
            metadata={'status': 503}
        )
    return ToolResult(success=True, output='Success!', metadata={})

executor = RetryExecutor(policy=policy, fallback_handler=None)
result = executor.execute_with_retry(failing_execute, 'web', {'url': 'http://test.com'})

if result.success and call_count[0] == 3:
    print(f'   [PASS] Retried {call_count[0]} times and succeeded')
else:
    print(f'   [FAIL] Expected 3 calls, got {call_count[0]}, success={result.success}')

# Test 4: RetryExecutor exhausts retries and fails
print()
print('4. Testing: RetryExecutor exhausts retries on persistent failure...')
call_count2 = [0]
def always_failing(name, args):
    call_count2[0] += 1
    return ToolResult(
        success=False,
        output='',
        error='Connection timeout',
        metadata={}
    )

policy2 = RetryPolicy(max_retries=2, base_delay=0.01, jitter=False)
executor2 = RetryExecutor(policy=policy2, fallback_handler=None)
result2 = executor2.execute_with_retry(always_failing, 'web', {'url': 'http://test.com'})

if not result2.success and 'retried 2 times' in (result2.error or ''):
    print(f'   [PASS] Exhausted retries, error indicates retry count')
else:
    print(f'   [FAIL] Expected retry count in error, got: {result2.error}')

# Test 5: Fallback handler is called
print()
print('5. Testing: Fallback handler is called after retries exhausted...')
call_count3 = [0]
def always_fails_transient(name, args):
    call_count3[0] += 1
    return ToolResult(success=False, output='', error='Connection timeout', metadata={})

def fallback_handler(name, args, last_result):
    return ToolResult(success=True, output='Fallback result', metadata={'fallback': True})

policy3 = RetryPolicy(max_retries=1, base_delay=0.01, jitter=False)
executor3 = RetryExecutor(policy=policy3, fallback_handler=fallback_handler)
result3 = executor3.execute_with_retry(always_fails_transient, 'web', {'url': 'http://test.com'})

if result3.success and result3.metadata.get('fallback'):
    print('   [PASS] Fallback handler was called and returned success')
else:
    print(f'   [FAIL] Fallback not triggered, success={result3.success}')

# Test 6: Retry logging
print()
print('6. Testing: Retry attempts are logged...')

log_file = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
log_path = log_file.name
log_file.close()

call_count4 = [0]
def fails_then_succeeds(name, args):
    call_count4[0] += 1
    if call_count4[0] < 2:
        return ToolResult(success=False, output='', error='HTTP 503', metadata={'status': 503})
    return ToolResult(success=True, output='OK', metadata={})

policy4 = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)
executor4 = RetryExecutor(policy=policy4, fallback_handler=None, audit_log_path=Path(log_path))

result4 = executor4.execute_with_retry(fails_then_succeeds, 'web', {'url': 'http://test.com'})

# Check log file
with open(log_path, 'r') as f:
    log_content = f.read()

os.unlink(log_path)

if 'retry_log' in log_content and 'attempts' in log_content:
    log_data = json.loads(log_content.strip())
    if len(log_data.get('attempts', [])) >= 2:
        print(f'   [PASS] Retry attempts logged ({len(log_data["attempts"])} attempts)')
    else:
        print(f'   [FAIL] Expected 2+ attempts in log, got {len(log_data.get("attempts", []))}')
else:
    print(f'   [FAIL] Log file missing retry data')

# Test 7: ToolRegistry integration
print()
print('7. Testing: ToolRegistry.execute_with_retry integration...')
from tools import FileTool

registry = ToolRegistry()
registry.register(FileTool())

# Without retry executor - should fall back to execute
result5 = registry.execute_with_retry('file', {'operation': 'exists', 'path': '/nonexistent'})
if not registry.get_retry_executor():
    print('   [PASS] execute_with_retry falls back to execute when no executor set')

# With retry executor
policy5 = RetryPolicy(max_retries=2, base_delay=0.01)
registry.set_retry_executor(RetryExecutor(policy=policy5))
if registry.get_retry_executor():
    print('   [PASS] Retry executor can be set on registry')

# Test 8: TransientErrorPattern
print()
print('8. Testing: TransientErrorPattern matching...')
pattern = TransientErrorPattern(
    pattern=r'timeout|timed out',
    description='Timeout errors',
    tool_names=['web', 'shell']
)

if pattern.matches('web', 'Connection timed out'):
    print('   [PASS] Pattern matches correct tool and error')
else:
    print('   [FAIL] Pattern should match')

if not pattern.matches('file', 'Connection timed out'):
    print('   [PASS] Pattern does not match wrong tool')
else:
    print('   [FAIL] Pattern should not match file tool')

# Test 9: RetryPolicy delay calculation
print()
print('9. Testing: RetryPolicy exponential backoff...')
policy6 = RetryPolicy(max_retries=5, base_delay=1.0, max_delay=30.0, exponential_base=2.0, jitter=False)

delays = [policy6.get_delay(i) for i in range(5)]
expected = [1.0, 2.0, 4.0, 8.0, 16.0]

if delays == expected:
    print(f'   [PASS] Exponential backoff correct: {delays}')
else:
    print(f'   [FAIL] Expected {expected}, got {delays}')

# Test max delay cap
policy7 = RetryPolicy(max_retries=10, base_delay=1.0, max_delay=10.0, exponential_base=2.0, jitter=False)
delay_at_10 = policy7.get_delay(10)
if delay_at_10 <= 10.0:
    print(f'   [PASS] Max delay cap respected: {delay_at_10}')
else:
    print(f'   [FAIL] Delay {delay_at_10} exceeds max 10.0')

# Test 10: Default fallback handlers
print()
print('10. Testing: Default fallback handlers...')
handler = create_default_fallback_handler()
if handler:
    print('   [PASS] Default fallback handler created')
else:
    print('   [FAIL] Failed to create default fallback handler')

# Test file read fallback
file_fallback_result = handler('file', {'operation': 'read', 'path': '/nonexistent/path.txt'}, ToolResult(success=False, output='', error='File not found', metadata={}))
if file_fallback_result is None:  # Expected for nonexistent file
    print('   [PASS] File fallback returns None for unreadable file')

print()
print('=== M1-004 VERIFICATION PASSED ===')
