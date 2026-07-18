"""Episode-level test metrics for GMDisturb co-simulation runs."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EpisodeMetrics:
    """Aggregated metrics for one disturbance-test episode."""

    episode_id: int = 0

    # Timing
    total_steps: int = 0
    policy_steps: int = 0           # UR10e policy clock

    # UR10e task
    parts_placed: int = 0
    parts_total: int = 20
    task_completed: bool = False

    # G1 state
    g1_fell: bool = False
    g1_root_z_min: float = 0.0
    g1_root_z_final: float = 0.0

    # Interventions (safety gate — populated in Phase 3+)
    tier0_stop_count: int = 0
    slowdown_count: int = 0
    replan_count: int = 0
    stuck_count: int = 0

    # D-group: disturbance effects (causal links from disturbance → response)
    d_stop_caused: int = 0    # disturbance attempts that resulted in STOP
    d_slow_caused: int = 0    # disturbance attempts that resulted in SLOW_DOWN
    d_replan_caused: int = 0  # disturbance attempts that triggered replan
    d_knock_off: int = 0      # parts knocked off (FK z < table_z - 0.05)

    # Mat events
    footstep_count: int = 0
    collision_count: int = 0
    object_drop_count: int = 0

    # Proximity
    min_g1_ur10e_distance_m: float = float("inf")     # XY centre-to-centre (controller view)
    min_surface_distance_m: float = float("inf")       # 3D surface-to-surface (adapter view — what safety gate actually uses)
    mean_g1_ur10e_distance_m: float = 0.0

    # F-group: safety response enhanced (2026-07-11)
    f_consecutive_stop_max: int = 0    # F09 — max consecutive STOP/SLOW steps (livelock indicator)
    f_replan_success: bool = False     # F07 — last replan attempt outcome
    f_replan_failure_reason: str = ""  # F08

    # H-group: VLM decision log (2026-07-11)
    h_vlm_action: str = ""             # H05 — last VLM disturbance action
    h_vlm_latency_ms: float = 0.0      # H09 — last VLM query latency
    h_vlm_reason: str = ""             # H08 — last VLM reasoning

    # Accumulators
    _distance_sum: float = field(default=0.0, repr=False)
    _consecutive_stop_cur: int = field(default=0, repr=False)  # F09 tracker

    # T1 fix: record the most recent safety gate decision so per-step
    # analysis can correlate disturbance behaviour with safety response.
    last_gate_decision: str = "N/A"
    last_gate_trigger: str = ""
    last_gate_distance: float = float("inf")
    last_closest_body: str = ""

    def record_step(
        self,
        *,
        g1_root_z: float,
        g1_ur10e_distance: float,
        surface_distance: float = float("inf"),
        mat_events: Optional[list] = None,
        gate_decision: Optional[str] = None,
        gate_trigger: str = "",
        gate_distance: float = float("inf"),
        closest_body: str = "",
        # D-group: disturbance effect causal inference (2026-07-11)
        disturbance_active: bool = False,
        # F-group: safety response enhanced (2026-07-11)
        consecutive_stop_count: int = 0,
        replan_success: Optional[bool] = None,
        replan_failure_reason: str = "",
        # H-group: VLM decision log (2026-07-11)
        vlm_action: str = "",
        vlm_latency_ms: float = 0.0,
        vlm_reason: str = "",
    ):
        """Update per-step accumulators."""
        self.total_steps += 1
        self.g1_root_z_min = min(self.g1_root_z_min, g1_root_z)
        self.g1_root_z_final = g1_root_z

        if g1_ur10e_distance < self.min_g1_ur10e_distance_m:
            self.min_g1_ur10e_distance_m = g1_ur10e_distance
        self._distance_sum += g1_ur10e_distance

        # Surface distance from safety adapter.
        if surface_distance < self.min_surface_distance_m:
            self.min_surface_distance_m = surface_distance

        # T1: persist latest safety gate state for CSV output
        if gate_decision is not None:
            self.last_gate_decision = str(gate_decision)
        if gate_trigger:
            self.last_gate_trigger = str(gate_trigger)
        if gate_distance != float("inf"):
            self.last_gate_distance = float(gate_distance)
        if closest_body:
            self.last_closest_body = str(closest_body)

        # D-group: disturbance effect causal inference
        if disturbance_active:
            if gate_decision == "STOP":
                self.d_stop_caused += 1
            elif gate_decision == "SLOW_DOWN":
                self.d_slow_caused += 1

        # F-group: livelock tracking (F09)
        self._consecutive_stop_cur = consecutive_stop_count
        if consecutive_stop_count > self.f_consecutive_stop_max:
            self.f_consecutive_stop_max = consecutive_stop_count

        # F-group: replan outcome (F07/F08)
        if replan_success is not None:
            self.f_replan_success = replan_success
            self.f_replan_failure_reason = replan_failure_reason
            if replan_success:
                self.d_replan_caused += 1

        # H-group: VLM decision log
        if vlm_action:
            self.h_vlm_action = vlm_action
        if vlm_latency_ms > 0:
            self.h_vlm_latency_ms = vlm_latency_ms
        if vlm_reason:
            self.h_vlm_reason = vlm_reason

        if mat_events:
            for ev in mat_events:
                if ev.event_type.startswith("footstep"):
                    self.footstep_count += 1
                elif ev.event_type == "collision_impact":
                    self.collision_count += 1
                elif ev.event_type == "object_drop":
                    self.object_drop_count += 1
                    # D-group: object drop during active disturbance
                    if disturbance_active:
                        self.d_knock_off += 1

    def finalise(self):
        """Compute derived fields after the episode ends."""
        if self.total_steps > 0:
            self.mean_g1_ur10e_distance_m = self._distance_sum / self.total_steps
        self.task_completed = self.parts_placed >= self.parts_total

    # ------------------------------------------------------------------
    # CSV output
    # ------------------------------------------------------------------

    _CSV_FIELDS = [
        "episode_id", "total_steps", "policy_steps",
        "parts_placed", "parts_total", "task_completed",
        "g1_fell", "g1_root_z_min", "g1_root_z_final",
        "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
        "d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off",
        "footstep_count", "collision_count", "object_drop_count",
        "min_g1_ur10e_distance_m", "min_surface_distance_m", "mean_g1_ur10e_distance_m",
        # T1: safety gate state at episode end (last recorded values)
        "last_gate_decision", "last_gate_trigger",
        "last_gate_distance", "last_closest_body",
        # F-group (2026-07-11)
        "f_consecutive_stop_max", "f_replan_success", "f_replan_failure_reason",
        # H-group (2026-07-11)
        "h_vlm_action", "h_vlm_latency_ms", "h_vlm_reason",
    ]

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self._CSV_FIELDS}

    def to_json_dict(self) -> dict:
        """All fields as JSON-serializable dict (for batch runner JSONL)."""
        d = self.as_dict()
        d["task_completed"] = bool(d.get("task_completed", False))
        d["g1_fell"] = bool(d.get("g1_fell", False))
        return d


class MetricsWriter:
    """Appends episode metrics to CSV and JSON files."""

    def __init__(self, path: str):
        self._path = path
        self._json_path = path.replace(".csv", ".jsonl")
        self._header_written = os.path.exists(path) and os.path.getsize(path) > 0

    def write(self, metrics: EpisodeMetrics):
        metrics.finalise()
        row = metrics.as_dict()
        with open(self._path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not self._header_written:
                writer.writeheader()
                self._header_written = True
            writer.writerow(row)
        # G-group: episode summary as JSONL (one line per episode).
        import json
        with open(self._json_path, "a") as f:
            f.write(json.dumps(metrics.to_json_dict(), default=str) + "\n")
