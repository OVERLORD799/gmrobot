"""Motion Replan data types (Phase 3.5 ADR contract)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pick_and_place_policy import SingleEnvPickAndPlacePolicy


@dataclass(frozen=True)
class ReplanHint:
    """绕行建议参数（几何 v0 或 VLM Stage 5 解析结果）。"""

    raise_approach_m: float = 0.25  # R7: was 0.05 — too low to trigger raise_high (>0.15m)
    lateral_offset_m: float = 0.10
    detour_stage_duration: int | None = None
    side: str = "auto"
    semantic_context: str | None = None
    vlm_confidence: float | None = None
    # v2: optional override; None → executor strategy selector
    detour_strategy: str | None = None


@dataclass(frozen=True)
class ReplanRequest:
    """Motion Replan 触发请求。"""

    request_id: str
    step_index: int
    task_time_step: int
    trigger_source: str
    trigger_rule: str
    dist_ee_human: float  # Deprecated; prefer ``dist_min``.  Legacy field name; semantic depended on caller (EE distance or envelope min).
    dist_min: float  # F24: canonical minimum distance used for gate threshold comparisons (dist_min_for_gating from rule engine).
    g_rule: int
    ee_pos: tuple[float, float, float]
    human_hand_pos: tuple[float, float, float]
    hint: ReplanHint | None
    created_at_s: float
    # Envelope audit fields (Phase 2.5b → replan v2 held-aware planning)
    dist_min_held: float | None = None
    dist_min_envelope: float | None = None
    closest_primitive_id: str | None = None
    hand_speed_mps: float | None = None
    # S13 P1: SAM2 /track kinematics (shadow-first; gated by use_perception_track_strategy).
    perception_track_speed_px_s: float | None = None
    perception_track_direction_deg: float | None = None
    use_perception_track_strategy: bool = False


@dataclass(frozen=True)
class ReplanResult:
    request_id: str
    status: str
    new_trajectory_len: int
    resume_time_step: int
    latency_ms: float
    post_replan_advance_until: int
    failure_reason: str | None = None


class MotionReplanExecutor(ABC):
    """修改 pick_and_place 路点序列；与门控并行、非阻塞。"""

    @abstractmethod
    def submit(self, request: ReplanRequest) -> str:
        """入队 replan 请求；返回 request_id。"""

    @abstractmethod
    def poll(self) -> ReplanResult | None:
        """非阻塞取已完成结果。"""

    @abstractmethod
    def apply(
        self,
        result: ReplanResult,
        policy: SingleEnvPickAndPlacePolicy,
    ) -> bool:
        """将新路点序列注入状态机。"""
