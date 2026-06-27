from collections import deque
from dataclasses import dataclass, field
import time
from app.registry.schemas import EndpointEntry

@dataclass
class _EndpointState:
    rpm_timestamps: deque = field(default_factory=deque)
    rpd_timestamps: deque = field(default_factory=deque)
    tpm_tokens: int = 0
    tpm_window_start: float = field(default_factory=time.time)
    cooldown_until: float | None = None
    consecutive_failures: int = 0

class EndpointRateLimiter:
    def __init__(self):
        self._state: dict[str, _EndpointState] = {}

    def _get(self, endpoint_id: str) -> _EndpointState:
        if endpoint_id not in self._state:
            self._state[endpoint_id] = _EndpointState()
        return self._state[endpoint_id]

    def _prune(self, state: _EndpointState) -> None:
        now = time.time()
        cutoff_rpm = now - 60
        cutoff_rpd = now - 86400
        while state.rpm_timestamps and state.rpm_timestamps[0] < cutoff_rpm:
            state.rpm_timestamps.popleft()
        while state.rpd_timestamps and state.rpd_timestamps[0] < cutoff_rpd:
            state.rpd_timestamps.popleft()

    def can_use(self, endpoint: EndpointEntry) -> bool:
        state = self._get(endpoint.id)
        self._prune(state)
        now = time.time()
        if state.cooldown_until and now < state.cooldown_until:
            return False
        if endpoint.rpm_limit and len(state.rpm_timestamps) >= 0.9 * endpoint.rpm_limit:
            return False
        if endpoint.rpd_limit and len(state.rpd_timestamps) >= 0.9 * endpoint.rpd_limit:
            return False
        return True

    def record_call(self, endpoint_id: str, token_count: int = 0) -> None:
        state = self._get(endpoint_id)
        self._prune(state)
        now = time.time()
        state.rpm_timestamps.append(now)
        state.rpd_timestamps.append(now)

    def record_429(self, endpoint_id: str, retry_after: int = 60) -> None:
        state = self._get(endpoint_id)
        state.cooldown_until = time.time() + retry_after
        state.consecutive_failures = 0

    def record_connect_failure(self, endpoint_id: str) -> None:
        state = self._get(endpoint_id)
        state.consecutive_failures += 1
        if state.consecutive_failures >= 2:
            state.cooldown_until = time.time() + 20  # dead-host cooldown

    def record_success(self, endpoint_id: str) -> None:
        self._get(endpoint_id).consecutive_failures = 0

    def usage_pct(self, endpoint: EndpointEntry) -> float:
        state = self._get(endpoint.id)
        self._prune(state)
        pcts = []
        if endpoint.rpm_limit:
            pcts.append(len(state.rpm_timestamps) / endpoint.rpm_limit)
        if endpoint.rpd_limit:
            pcts.append(len(state.rpd_timestamps) / endpoint.rpd_limit)
        return max(pcts) if pcts else 0.0
