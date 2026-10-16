"""In-process counters. There is no metrics service in this phase."""
from collections import defaultdict
import threading

_lock = threading.Lock()
investigation_runs_total: dict[str, int] = defaultdict(int)
specialist_duration_ms: dict[str, list[float]] = defaultdict(list)
citation_rejected_total = 0
decision_language_dropped_total = 0


def record_run(status: str) -> None:
    with _lock:
        investigation_runs_total[status] += 1


def record_specialist_duration(specialist: str, duration_ms: float) -> None:
    with _lock:
        specialist_duration_ms[specialist].append(duration_ms)


def record_citation_rejected() -> None:
    global citation_rejected_total
    with _lock:
        citation_rejected_total += 1


def record_decision_drop() -> None:
    global decision_language_dropped_total
    with _lock:
        decision_language_dropped_total += 1
