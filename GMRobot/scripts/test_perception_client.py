#!/usr/bin/env python3
"""Smoke test for PerceptionClient (no Isaac; optional live tunnel on :18082)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
# Import perception subpackage only (avoid GMRobot.tasks → isaaclab).
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
from perception import PerceptionClient, PerceptionTrackSession


def main() -> int:
    parser = argparse.ArgumentParser(description="Test GDINO+SAM2 perception client.")
    parser.add_argument(
        "--config",
        type=str,
        default=str(ROOT / "configs" / "perception_client.yaml"),
        help="Path to perception_client.yaml",
    )
    parser.add_argument(
        "--skip-ground",
        action="store_true",
        help="Only run /health (skip slow /ground).",
    )
    parser.add_argument(
        "--track",
        action="store_true",
        help="Run /track init+step smoke after /ground (or alone with --skip-ground).",
    )
    args = parser.parse_args()

    client = PerceptionClient.from_yaml(args.config)
    print(f"[INFO] base_url={client.config.base_url}")

    health = client.health_check()
    print(f"[HEALTH] {health}")
    if health.get("ok") is False or "error" in health and health.get("status") is None:
        print("[FAIL] health check failed (is SSH tunnel :18082 up?)")
        return 1

    if args.skip_ground and not args.track:
        print("[OK] health only")
        return 0

    rgb_a = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    rgb_b = rgb_a.copy()
    rgb_b[:, 10:, :] = np.clip(rgb_b[:, 10:, :].astype(np.int16) + 5, 0, 255).astype(
        np.uint8
    )

    seed_box = None
    if not args.skip_ground:
        result = client.ground(rgb_a, meta={"smoke": True})
        if result.get("ok") is False:
            print(f"[FAIL] /ground error: {result}")
            return 1

        n_det = len(result.get("detections", []))
        latency = result.get("latency_ms", "n/a")
        print(f"[GROUND] detections={n_det} latency_ms={latency}")
        dets = result.get("detections") or []
        if dets:
            best = max(dets, key=lambda d: float(d.get("score", 0) or 0))
            seed_box = best.get("box_xyxy")

    if args.track:
        session = PerceptionTrackSession()
        init_result, session = client.track_frame(
            rgb_a, session, box_xyxy=seed_box, meta={"smoke": True, "frame": 0}
        )
        if init_result.get("ok") is False or init_result.get("error"):
            print(f"[FAIL] /track init error: {init_result}")
            return 1
        step_result, session = client.track_frame(
            rgb_b, session, meta={"smoke": True, "frame": 1}
        )
        if step_result.get("ok") is False or step_result.get("error"):
            print(f"[FAIL] /track step error: {step_result}")
            return 1
        primary = client.pick_primary_track(step_result)
        if primary:
            primary = client.enrich_track_kinematics(
                primary, session=session, dt_s=client.config.track_dt_s
            )
        n_tracks = len(step_result.get("tracks", []))
        speed = (primary or {}).get("speed_px_s", "n/a")
        print(
            f"[TRACK] session={session.session_id} tracks={n_tracks} "
            f"speed_px_s={speed} latency_ms={step_result.get('latency_ms', 'n/a')}"
        )

    print("[OK] perception client smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
