"""Cost and latency observability monitor (M5-002)."""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0.0, min(100.0, float(p))) / 100.0 * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    frac = rank - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


class CostLatencyMonitor:
    """Analyze audit logs for cost, latency, and budget alerts."""

    def __init__(
        self,
        status_file: Path,
        token_cost_per_1k: float = 0.01,
        tool_call_cost: float = 0.0,
        budget_threshold: float = 50.0,
    ):
        self.status_file = Path(status_file)
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_cost_per_1k = max(0.0, float(token_cost_per_1k))
        self.tool_call_cost = max(0.0, float(tool_call_cost))
        self.budget_threshold = max(0.0, float(budget_threshold))

    def _write_status(self, payload: Dict[str, Any]) -> None:
        temp = self.status_file.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temp.replace(self.status_file)

    def analyze_audit_log(self, audit_log_path: Path) -> Dict[str, Any]:
        path = Path(audit_log_path)
        events: List[Dict[str, Any]] = []
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        events.append(row)

        model_latencies: List[float] = []
        tool_latencies: List[float] = []
        total_tokens = 0
        tool_calls = 0

        for event in events:
            event_type = str(event.get("event_type", ""))
            if event_type == "model_response":
                latency = event.get("latency_ms")
                if isinstance(latency, (int, float)):
                    model_latencies.append(float(latency))
                total = event.get("total_tokens")
                if isinstance(total, (int, float)) and total > 0:
                    total_tokens += int(total)
            elif event_type == "tool_result":
                tool_calls += 1
                latency = event.get("latency_ms")
                if isinstance(latency, (int, float)):
                    tool_latencies.append(float(latency))
            elif event_type == "tool_call":
                tool_calls += 1

        # If both tool_call and tool_result exist, estimate unique tool calls by halving pairs.
        if tool_calls > 0:
            tool_calls = max(1, tool_calls // 2) if any(e.get("event_type") == "tool_result" for e in events) else tool_calls

        token_cost = round((total_tokens / 1000.0) * self.token_cost_per_1k, 6)
        tool_cost = round(tool_calls * self.tool_call_cost, 6)
        total_cost = round(token_cost + tool_cost, 6)

        all_latencies = model_latencies + tool_latencies
        p50_latency_ms = round(_percentile(all_latencies, 50), 2)
        p95_latency_ms = round(_percentile(all_latencies, 95), 2)

        alerts: List[str] = []
        if self.budget_threshold > 0 and total_cost >= self.budget_threshold:
            alerts.append(
                "budget threshold exceeded: "
                f"cost={total_cost} threshold={self.budget_threshold}"
            )

        status = {
            "ok": len(alerts) == 0,
            "status": "healthy" if len(alerts) == 0 else "degraded",
            "alerts": alerts,
            "metrics": {
                "event_count": len(events),
                "total_tokens": total_tokens,
                "tool_calls": tool_calls,
                "token_cost": token_cost,
                "tool_cost": tool_cost,
                "total_cost": total_cost,
                "p50_latency_ms": p50_latency_ms,
                "p95_latency_ms": p95_latency_ms,
                "model_latency_samples": len(model_latencies),
                "tool_latency_samples": len(tool_latencies),
            },
        }
        self._write_status(status)
        return status
