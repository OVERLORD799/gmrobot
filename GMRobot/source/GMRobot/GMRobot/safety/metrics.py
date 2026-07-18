"""Aggregate safety intervention metrics (paper IV-H)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import GateDecision


@dataclass
class SafetyMetrics:
    """Track intervention rate, duration, replan success, and livelock metrics."""

    total_steps: int = 0
    stop_steps: int = 0
    slow_steps: int = 0
    stop_run_lengths: list[int] = field(default_factory=list)
    _current_stop_run: int = 0
    episodes_completed: int = 0
    episodes_success: int = 0
    # Replan outcome counters (W8).
    replan_triggers: int = 0
    replan_applied: int = 0
    replan_failed: int = 0
    # Post-replan collision tracking.
    steps_after_replan: int = 0
    post_replan_collision_steps: int = 0
    _replan_applied_this_episode: bool = False

    def record_step(self, g_t: GateDecision) -> None:
        self.total_steps += 1
        if g_t == GateDecision.STOP:
            self.stop_steps += 1
            self._current_stop_run += 1
        else:
            if self._current_stop_run > 0:
                self.stop_run_lengths.append(self._current_stop_run)
            self._current_stop_run = 0
        if g_t == GateDecision.SLOW_DOWN:
            self.slow_steps += 1
        if self._replan_applied_this_episode:
            self.steps_after_replan += 1
            if g_t == GateDecision.STOP:
                self.post_replan_collision_steps += 1

    def record_replan_event(self, event: str) -> None:
        """Track replan trigger / apply / fail per step (W8)."""
        if event == "trigger":
            self.replan_triggers += 1
        elif event == "applied":
            self.replan_applied += 1
            self._replan_applied_this_episode = True
        elif event == "failed":
            self.replan_failed += 1

    def record_episode_success(self, success: bool) -> None:
        self.episodes_completed += 1
        if success:
            self.episodes_success += 1

    def finalize(self) -> None:
        if self._current_stop_run > 0:
            self.stop_run_lengths.append(self._current_stop_run)
            self._current_stop_run = 0

    @property
    def current_consecutive_stop(self) -> int:
        return self._current_stop_run

    @property
    def max_consecutive_stop(self) -> int:
        if not self.stop_run_lengths:
            return 0
        return max(self.stop_run_lengths)

    @property
    def intervention_rate(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return self.stop_steps / self.total_steps

    @property
    def slow_down_rate(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return self.slow_steps / self.total_steps

    @property
    def replan_success_rate(self) -> float:
        if self.replan_triggers == 0:
            return 0.0
        return self.replan_applied / self.replan_triggers

    @property
    def post_replan_collision_rate(self) -> float:
        if self.steps_after_replan == 0:
            return 0.0
        return self.post_replan_collision_steps / self.steps_after_replan

    @property
    def mean_stop_duration_steps(self) -> float:
        if not self.stop_run_lengths:
            return 0.0
        return sum(self.stop_run_lengths) / len(self.stop_run_lengths)

    @property
    def success_rate(self) -> float:
        if self.episodes_completed == 0:
            return 0.0
        return self.episodes_success / self.episodes_completed

    @property
    def livelock_ratio(self) -> float:
        """Fraction of STOP runs exceeding a heuristic livelock threshold (≥ 50 steps)."""
        if not self.stop_run_lengths:
            return 0.0
        long_runs = sum(1 for r in self.stop_run_lengths if r >= 50)
        return long_runs / len(self.stop_run_lengths)

    def summary(self) -> dict[str, float]:
        self.finalize()
        return {
            "intervention_rate": self.intervention_rate,
            "slow_down_rate": self.slow_down_rate,
            "mean_stop_duration_steps": self.mean_stop_duration_steps,
            "max_consecutive_stop": float(self.max_consecutive_stop),
            "livelock_ratio": self.livelock_ratio,
            "replan_success_rate": self.replan_success_rate,
            "post_replan_collision_rate": self.post_replan_collision_rate,
            "success_rate": self.success_rate,
            "total_steps": float(self.total_steps),
            "stop_steps": float(self.stop_steps),
        }
