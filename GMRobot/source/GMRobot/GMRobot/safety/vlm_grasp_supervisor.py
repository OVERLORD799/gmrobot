"""VLM-based global supervision for object grasp / carry state.

During carry phases the system currently assumes the object stays held once
``mark_grasp_hold_validated()`` fires — it has no way to detect mid-carry
knock-off.  This module calls the existing VLM with a dedicated prompt that
asks whether an object is visible in / near the gripper, and triggers a
carry abort when high-confidence loss is confirmed over consecutive checks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Prompt sent to the VLM (overrides the default safety-risk prompt via the
# ``prompt`` parameter of VLMClient.analyze).
# ---------------------------------------------------------------------------
GRASP_CHECK_PROMPT = (
    "Look at the robot gripper area. Is the gripper holding or carrying "
    "a box-shaped object (cube / block / part)? "
    "Reply with ONLY valid JSON, no extra text: "
    '{"object_held": true/false, "confidence": 0.0-1.0, "description": "brief"}'
)

# Scene-level inventory prompt: count and locate ALL visible parts.
# Called less frequently than the gripper check (e.g. every 500 steps).
SCENE_INVENTORY_PROMPT = (
    "Look at the entire scene. Count how many box/cube-shaped objects (parts) "
    "you can see and describe where each one is. Pay attention to:\n"
    "- Objects held in the robot gripper\n"
    "- Objects on the left side (source/pick area)\n"
    "- Objects on the right side (target/place area)\n"
    "- Objects on the ground or elsewhere\n"
    "Reply with ONLY valid JSON, no extra text:\n"
    '{"total_parts": N, "parts": [{"label": "A"|"B"|..., "location": "gripper"|"source"|"target"|"elsewhere", "confidence": 0.0-1.0}]}'
)

# How many *consecutive* high-confidence "lost" VLM results are required
# before the supervisor signals a carry abort.  This filters transient VLM
# flips caused by occlusions, motion blur, or lighting changes.
_CONSECUTIVE_LOST_THRESHOLD: int = 3


@dataclass
class VLMGraspCheckResult:
    """Structured result from one VLM grasp check."""

    object_held: bool = True
    confidence: float = 0.0
    description: str = ""
    raw_explanation: str = ""
    latency_ms: float = 0.0
    ok: bool = False
    skipped: bool = True  # True when the check was not run this step


@dataclass
class SceneInventoryResult:
    """Structured result from one VLM scene inventory check."""

    total_parts: int = 0
    parts_in_gripper: int = 0
    parts_in_source: int = 0
    parts_in_target: int = 0
    parts_elsewhere: int = 0
    part_labels: list[dict[str, Any]] = field(default_factory=list)
    raw_explanation: str = ""
    latency_ms: float = 0.0
    ok: bool = False
    skipped: bool = True


@dataclass
class VLMGraspSupervisorConfig:
    """Configuration for the VLM grasp supervisor."""

    enabled: bool = False
    interval: int = 100       # call VLM every N control steps during carry
    scene_interval: int = 500  # call VLM for full scene inventory every N steps
    confidence_threshold: float = 0.7  # min confidence to act on "lost" / "held"
    consecutive_lost: int = _CONSECUTIVE_LOST_THRESHOLD


class VLMGraspSupervisor:
    """Periodically checks via VLM whether the grasped object is still held.

    Usage (per-step in the main loop)::

        result = supervisor.check(
            vlm_client, rgb_frame, step=step_counter,
            is_carrying=held_object_active,
        )
        if result is not None:
            ... log fields ...

        if supervisor.should_abort_carry():
            policy.mark_carry_aborted()  # or equivalent recovery action
    """

    def __init__(self, config: VLMGraspSupervisorConfig | None = None):
        self.config = config or VLMGraspSupervisorConfig()
        self._step_counter: int = 0
        self._consecutive_lost: int = 0
        self._last_result: VLMGraspCheckResult | None = None
        self._last_inventory: SceneInventoryResult | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_scene_inventory(
        self,
        vlm_client: Any,
        rgb_frame: np.ndarray,
        *,
        step: int,
        meta: dict[str, Any] | None = None,
    ) -> SceneInventoryResult | None:
        """Run a full-scene VLM part inventory check.

        Called less frequently than the gripper check (default every 500 steps).
        Returns ``None`` when skipped, otherwise a structured inventory result.
        """
        self._step_counter = step

        if not self.config.enabled or vlm_client is None:
            return None
        interval = max(1, self.config.scene_interval)
        if step % interval != 0:
            return None

        result = self._call_scene_vlm(vlm_client, rgb_frame, meta=meta)
        self._last_inventory = result
        return result

    def last_inventory(self) -> SceneInventoryResult | None:
        return self._last_inventory

    def check(
        self,
        vlm_client: Any,
        rgb_frame: np.ndarray,
        *,
        step: int,
        is_carrying: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> VLMGraspCheckResult | None:
        """Run a VLM grasp check if the interval and phase allow.

        Returns ``None`` when the check is skipped (interval not reached,
        not in carry phase, or VLM client missing).  Otherwise returns a
        structured result whose ``object_held`` field is the VLM's belief.
        """
        self._step_counter = step

        if not self.config.enabled or vlm_client is None:
            return None
        if not is_carrying:
            # Outside carry window — reset accumulator so stale "lost" flags
            # don't bleed into the next pick.
            self._consecutive_lost = 0
            return None
        if self.config.interval <= 0 or step % self.config.interval != 0:
            return None

        result = self._call_vlm(vlm_client, rgb_frame, meta=meta)
        self._last_result = result

        if result.ok:
            if not result.object_held and result.confidence >= self.config.confidence_threshold:
                self._consecutive_lost += 1
            else:
                self._consecutive_lost = 0

        return result

    def should_abort_carry(self) -> bool:
        """True when consecutive high-confidence "lost" checks meet the threshold."""
        return self._consecutive_lost >= self.config.consecutive_lost

    def last_result(self) -> VLMGraspCheckResult | None:
        return self._last_result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_vlm(
        self,
        vlm_client: Any,
        rgb_frame: np.ndarray,
        *,
        meta: dict[str, Any] | None = None,
    ) -> VLMGraspCheckResult:
        """Send the grasp-check prompt and parse the response."""
        try:
            raw = vlm_client.analyze(
                rgb_frame,
                prompt=GRASP_CHECK_PROMPT,
                meta=meta or {},
            )
        except Exception as exc:
            return VLMGraspCheckResult(
                ok=False,
                skipped=False,
                raw_explanation=str(exc),
            )

        if not raw.get("ok"):
            return VLMGraspCheckResult(
                ok=False,
                skipped=False,
                raw_explanation=raw.get("error", str(raw)),
                latency_ms=float(raw.get("vlm_latency_ms", 0)),
            )

        explanation = raw.get("vlm_explanation", "")
        parsed = _parse_grasp_json(explanation)

        return VLMGraspCheckResult(
            object_held=parsed.get("object_held", True),
            confidence=float(parsed.get("confidence", 0.0)),
            description=str(parsed.get("description", "")),
            raw_explanation=explanation,
            latency_ms=float(raw.get("vlm_latency_ms", 0)),
            ok=True,
            skipped=False,
        )

    def _call_scene_vlm(
        self,
        vlm_client: Any,
        rgb_frame: np.ndarray,
        *,
        meta: dict[str, Any] | None = None,
    ) -> SceneInventoryResult:
        """Send the scene-inventory prompt and parse the response."""
        try:
            raw = vlm_client.analyze(
                rgb_frame,
                prompt=SCENE_INVENTORY_PROMPT,
                meta=meta or {},
            )
        except Exception as exc:
            return SceneInventoryResult(
                ok=False,
                skipped=False,
                raw_explanation=str(exc),
            )

        if not raw.get("ok"):
            return SceneInventoryResult(
                ok=False,
                skipped=False,
                raw_explanation=raw.get("error", str(raw)),
                latency_ms=float(raw.get("vlm_latency_ms", 0)),
            )

        explanation = raw.get("vlm_explanation", "")
        parsed = _parse_grasp_json(explanation)

        parts: list[dict[str, Any]] = parsed.get("parts", [])
        parts_in_gripper = sum(
            1 for p in parts
            if isinstance(p, dict) and str(p.get("location", "")).lower() == "gripper"
        )
        parts_in_source = sum(
            1 for p in parts
            if isinstance(p, dict) and str(p.get("location", "")).lower() == "source"
        )
        parts_in_target = sum(
            1 for p in parts
            if isinstance(p, dict) and str(p.get("location", "")).lower() == "target"
        )
        parts_elsewhere = sum(
            1 for p in parts
            if isinstance(p, dict)
            and str(p.get("location", "")).lower() not in ("gripper", "source", "target")
        )

        total = parsed.get("total_parts", len(parts))
        if not isinstance(total, int) or total <= 0:
            total = len(parts)

        return SceneInventoryResult(
            total_parts=int(total),
            parts_in_gripper=parts_in_gripper,
            parts_in_source=parts_in_source,
            parts_in_target=parts_in_target,
            parts_elsewhere=parts_elsewhere,
            part_labels=parts,
            raw_explanation=explanation,
            latency_ms=float(raw.get("vlm_latency_ms", 0)),
            ok=True,
            skipped=False,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Updated columns for the grasp supervisor (key → default).
_GRASP_SUPERVISOR_COLUMN_KEYS = (
    "vlm_object_held",
    "vlm_object_held_confidence",
    "vlm_object_held_desc",
    "vlm_grasp_lost_streak",
)
_GRASP_SUPERVISOR_RESERVED: dict[str, str] = {
    key: "" for key in _GRASP_SUPERVISOR_COLUMN_KEYS
}


def grasp_supervisor_log_fields(
    supervisor: VLMGraspSupervisor | None,
) -> dict[str, str]:
    """Map the supervisor's last result to SafetyLogger CSV columns."""
    if supervisor is None:
        return dict(_GRASP_SUPERVISOR_RESERVED)

    result = supervisor.last_result()
    if result is None or result.skipped:
        # No check this step — forward-fill the loss streak so the CSV
        # always carries the accumulator state.
        return {
            "vlm_object_held": "",
            "vlm_object_held_confidence": "",
            "vlm_object_held_desc": "",
            "vlm_grasp_lost_streak": str(supervisor._consecutive_lost) if supervisor is not None else "",
        }

    return {
        "vlm_object_held": "1" if result.object_held else "0",
        "vlm_object_held_confidence": str(result.confidence),
        "vlm_object_held_desc": result.description,
        "vlm_grasp_lost_streak": str(supervisor._consecutive_lost),
    }


def scene_inventory_log_fields(
    supervisor: VLMGraspSupervisor | None,
) -> dict[str, str]:
    """Map the supervisor's last scene inventory to SafetyLogger CSV columns."""
    if supervisor is None:
        return {
            "vlm_scene_total_parts": "",
            "vlm_scene_parts_in_gripper": "",
            "vlm_scene_parts_in_source": "",
            "vlm_scene_parts_in_target": "",
            "vlm_scene_parts_elsewhere": "",
            "vlm_scene_inventory_latency_ms": "",
        }

    inv = supervisor.last_inventory()
    if inv is None or inv.skipped:
        return {
            "vlm_scene_total_parts": "",
            "vlm_scene_parts_in_gripper": "",
            "vlm_scene_parts_in_source": "",
            "vlm_scene_parts_in_target": "",
            "vlm_scene_parts_elsewhere": "",
            "vlm_scene_inventory_latency_ms": "",
        }

    return {
        "vlm_scene_total_parts": str(inv.total_parts),
        "vlm_scene_parts_in_gripper": str(inv.parts_in_gripper),
        "vlm_scene_parts_in_source": str(inv.parts_in_source),
        "vlm_scene_parts_in_target": str(inv.parts_in_target),
        "vlm_scene_parts_elsewhere": str(inv.parts_elsewhere),
        "vlm_scene_inventory_latency_ms": str(inv.latency_ms),
    }


def _parse_grasp_json(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object using brace counting.

    Handles nested objects and arrays (e.g. ``{"parts": [{"label": "A"}]}``)
    correctly, unlike the old regex ``r\"\\{[^{}]*\\}\"``.
    """
    if not text:
        return {}

    # Strip markdown code fences.
    cleaned = re.sub(r"```(?:json)?\s*", "", text, count=1)
    cleaned = cleaned.replace("```", "")

    start = cleaned.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    # Unclosed brace — fallback to regex for flat objects.
    m = re.search(r"\{[^{}]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}
