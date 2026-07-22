#!/usr/bin/env python3
"""V0-B4 formal Legacy Gateway two-frame replay (hard-capped POSTs).

Default dry-run. ``--execute`` performs at most 6 POSTs via formal
VLMClient/PerceptionClient/Legacy*Gateway/FiveStageShadowWorker/Logger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source" / "GMRobot" / "GMRobot"))
sys.path.insert(0, str(ROOT / "source" / "GMRobot"))

from perception.client import PerceptionClient  # noqa: E402
from shadow.five_stage_worker import FiveStageShadowWorker  # noqa: E402
from shadow.logger import FiveStageShadowLogger  # noqa: E402
from vlm.client import VLMClient  # noqa: E402

MAX_POSTS = 6
STAGE_LIMITS = {
    "vlm_analyze": 2,
    "ground": 2,
    "track_init": 1,
    "track_step": 1,
}


class ReplayError(RuntimeError):
    pass


class BudgetError(ReplayError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rgb(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {"image_b64", "imageb64", "authorization", "password", "token"}:
                out[k] = "<redacted>"
            elif lk in {"session_id"} and isinstance(v, str) and v and v != "<redacted>":
                out[k] = "<redacted>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, str) and len(obj) > 4096:
        return obj[:4096] + "...<truncated>"
    return obj


def load_artifact_shas(manifest: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with manifest.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            name = Path(str(rec["image_path"])).name
            out[name] = str(rec["sha256"])
    return out


@dataclass
class RequestBudget:
    ledger_path: Path
    max_posts: int = MAX_POSTS
    stage_limits: dict[str, int] = field(default_factory=lambda: dict(STAGE_LIMITS))
    _count: int = 0
    _stage_counts: dict[str, int] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, path: Path) -> "RequestBudget":
        if path.exists():
            raise ReplayError(f"ledger exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=False)
        return cls(ledger_path=path)

    def _append(self, rec: dict[str, Any]) -> None:
        safe = {k: v for k, v in rec.items() if k not in {"image_b64", "session_id", "Authorization"}}
        line = json.dumps(safe, ensure_ascii=False) + "\n"
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        self.history.append(safe)

    def classify(self, endpoint: str, body: dict[str, Any] | None) -> str:
        ep = endpoint.rstrip("/").split("/")[-1]
        if ep == "analyze" or endpoint.endswith("/analyze"):
            return "vlm_analyze"
        if ep == "ground" or endpoint.endswith("/ground"):
            return "ground"
        if ep == "track" or endpoint.endswith("/track"):
            action = str((body or {}).get("action") or "").lower()
            if action == "init":
                return "track_init"
            if action == "step":
                return "track_step"
            raise BudgetError(f"unknown track action={action!r}")
        raise BudgetError(f"unclassified endpoint={endpoint!r}")

    def plan(self, stage: str, *, request_id: str = "", frame_id: str = "", image_sha256: str = "") -> int:
        if self._count >= self.max_posts:
            raise BudgetError(f"POST budget exhausted ({self.max_posts})")
        used = self._stage_counts.get(stage, 0)
        limit = self.stage_limits.get(stage, 0)
        if used >= limit:
            raise BudgetError(f"stage budget exhausted: {stage} ({used}/{limit})")
        idx = self._count + 1
        self._append(
            {
                "request_index": idx,
                "endpoint_alias": stage,
                "request_id": request_id,
                "frame_id": frame_id,
                "image_sha256": image_sha256,
                "planned_at": utc_now(),
                "status": "planned",
            }
        )
        self._stage_counts[stage] = used + 1
        self._count += 1
        return idx

    def finalize(
        self,
        request_index: int,
        *,
        status: str,
        http_status: int | None = None,
        elapsed_s: float | None = None,
        error: str | None = None,
    ) -> None:
        self._append(
            {
                "request_index": request_index,
                "status": status,
                "finalized_at": utc_now(),
                "http_status": http_status,
                "elapsed_s": elapsed_s,
                "error": error,
            }
        )


def wrap_client_http(
    client: Any,
    budget: RequestBudget,
    *,
    get_context: Callable[[], dict[str, str]],
) -> None:
    """Wrap client._request_json so every POST is ledgered and budgeted."""
    orig = client._request_json

    def _wrapped(method: str, endpoint: str, *, body: dict[str, Any] | None = None):
        if str(method).upper() != "POST":
            return orig(method, endpoint, body=body)
        stage = budget.classify(endpoint, body)
        ctx = get_context()
        idx = budget.plan(
            stage,
            request_id=ctx.get("request_id", ""),
            frame_id=ctx.get("frame_id", ""),
            image_sha256=ctx.get("image_sha256", ""),
        )
        t0 = time.perf_counter()
        try:
            result = orig(method, endpoint, body=body)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - t0
            msg = str(exc).lower()
            status = "timeout" if "timed out" in msg or "timeout" in msg else "failed"
            budget.finalize(idx, status=status, http_status=0, elapsed_s=elapsed, error=str(exc)[:300])
            raise
        elapsed = time.perf_counter() - t0
        # Infer HTTP-ish outcome from structured client errors
        if isinstance(result, dict) and (
            result.get("ok") is False
            and str(result.get("error_type") or "") in {"timeout", "transport_error"}
            or (result.get("error") and "timed out" in str(result.get("error")).lower())
        ):
            et = str(result.get("error_type") or "")
            status = "timeout" if et == "timeout" or "timed out" in str(result.get("error") or "").lower() else "failed"
            budget.finalize(
                idx,
                status=status,
                http_status=0,
                elapsed_s=elapsed,
                error=str(result.get("error") or et)[:300],
            )
            return result
        budget.finalize(idx, status="completed", http_status=200, elapsed_s=elapsed)
        return result

    client._request_json = _wrapped  # type: ignore[method-assign]


def wait_for_result(
    worker: FiveStageShadowWorker,
    *,
    request_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        res = worker.latest_result()
        if res and str(res.get("request_id")) == str(request_id):
            return res
        time.sleep(0.05)
    raise ReplayError(f"timeout waiting for request_id={request_id}")


def classify_failure(frame_idx: int, result: dict[str, Any] | None, *, stage_hint: str = "") -> str:
    if stage_hint == "BUDGET_VIOLATION":
        return "BUDGET_VIOLATION"
    if stage_hint == "CONTROL_LEAKAGE":
        return "CONTROL_LEAKAGE"
    if not result:
        return "VLM_FAIL"
    vlm = result.get("vlm") or {}
    ground = result.get("ground") or {}
    track = result.get("track")
    if vlm.get("ok") is not True:
        return "VLM_FAIL"
    dets = ground.get("detections") or []
    if ground.get("ok") is False or not dets:
        if ground.get("perception_status") == "skipped_no_keywords":
            return "VLM_FAIL"
        return "GROUND_FAIL"
    if not track or track.get("ok") is False:
        return "TRACK_INIT_FAIL" if frame_idx == 0 else "TRACK_STEP_FAIL"
    state = str(result.get("track_state") or track.get("track_state") or "")
    if frame_idx == 0 and state != "initialized":
        return "TRACK_INIT_FAIL"
    if frame_idx == 1 and state != "tracking":
        return "TRACK_STEP_FAIL"
    return ""


def validate_frame(
    result: dict[str, Any],
    *,
    frame_idx: int,
    expected_request_id: str,
    expected_frame_id: str,
    prev_track_id: Any = None,
) -> list[str]:
    errs: list[str] = []
    if str(result.get("request_id")) != str(expected_request_id):
        errs.append("request_id_mismatch")
    if str(result.get("frame_id")) != str(expected_frame_id):
        errs.append("frame_id_mismatch")
    vlm = result.get("vlm") or {}
    if vlm.get("ok") is not True:
        errs.append(f"vlm_not_ok:{vlm.get('error_type')}")
        return errs
    if str(vlm.get("request_id")) != str(expected_request_id):
        errs.append("vlm_request_id_mismatch")
    if str(vlm.get("frame_id")) != str(expected_frame_id):
        errs.append("vlm_frame_id_mismatch")
    for fld in (
        "predicted_consequence",
        "prediction_horizon_s",
        "spatial_hint",
        "keywords",
        "risk_type",
        "suggested_action",
    ):
        if fld not in vlm:
            errs.append(f"vlm_missing_{fld}")
    keywords = list(result.get("keywords") or vlm.get("keywords") or [])
    if not keywords:
        errs.append("keywords_empty")

    ground = result.get("ground") or {}
    if str(ground.get("parent_request_id") or "") != str(expected_request_id):
        errs.append("ground_parent_mismatch")
    dets = ground.get("detections") or []
    if not isinstance(dets, list) or not dets:
        errs.append("detections_empty")
    mv = ground.get("model_versions") or {}
    gdino = str(mv.get("gdino_model_id") or "")
    sam2 = str(mv.get("sam2_model_id") or mv.get("sam2_checkpoint") or "")
    for name, val in (("gdino", gdino), ("sam2", sam2)):
        low = val.lower()
        if not val or any(x in low for x in ("fake", "mock", "test")):
            errs.append(f"{name}_model_invalid")

    track = result.get("track") or {}
    if str(track.get("parent_request_id") or result.get("parent_request_id") or "") != str(
        expected_request_id
    ):
        # worker sets parent_request_id on result; track may also
        if str(result.get("parent_request_id") or "") != str(expected_request_id):
            errs.append("track_parent_mismatch")
    if str(result.get("id_source") or vlm.get("id_source") or "") != "local_gateway":
        # accept if nested
        if str(vlm.get("id_source")) != "local_gateway" and str(ground.get("id_source")) != "local_gateway":
            errs.append("id_source_not_local_gateway")

    tid = result.get("track_id")
    if tid is None or (isinstance(tid, str) and tid.strip() == ""):
        errs.append("track_id_missing")
    else:
        try:
            int(tid)  # track_id=0 is valid
        except (TypeError, ValueError):
            if str(tid).strip() == "":
                errs.append("track_id_invalid")

    tracks = track.get("tracks") or []
    primary = tracks[0] if tracks and isinstance(tracks[0], dict) else {}
    state = str(result.get("track_state") or track.get("track_state") or "")

    if frame_idx == 0:
        if state != "initialized":
            errs.append(f"expected_initialized_got_{state}")
        # keyword-match preference applies to track *init* selection only
        label = str(primary.get("label") or "")
        if label.strip() and keywords:
            lab = label.lower()
            if not any(k.lower() in lab or lab in k.lower() for k in keywords):
                errs.append("selected_label_not_keyword_matched")
    else:
        # track step: session/track continuity — do NOT re-require VLM keyword match
        if not tracks:
            errs.append("step_tracks_empty")
            if state not in {"lost", "tracking"}:
                errs.append(f"expected_tracking_or_lost_got_{state}")
        elif state != "tracking":
            errs.append(f"expected_tracking_got_{state}")
        if prev_track_id is not None and tid is not None and str(tid).strip() != "":
            try:
                if int(tid) != int(prev_track_id):
                    errs.append("track_id_not_associated_across_frames")
            except (TypeError, ValueError):
                if str(tid) != str(prev_track_id):
                    errs.append("track_id_not_associated_across_frames")
        session_ok = bool(track.get("session_present")) or bool(result.get("track_session_id"))
        if track.get("session_match") is False:
            errs.append("session_mismatch")
        elif not session_ok:
            errs.append("session_missing_on_step")

    if result.get("track_state_native") is not False:
        errs.append("track_state_native_must_be_false")
    if str(result.get("track_state_source") or "") != "legacy_gateway_inferred":
        if str(track.get("track_state_source") or "") != "legacy_gateway_inferred":
            errs.append("track_state_source_mismatch")

    # mask/score/box from primary track when present
    if primary:
        box = primary.get("box_xyxy")
        if not (isinstance(box, (list, tuple)) and len(box) == 4):
            errs.append("box_xyxy_invalid")
        try:
            mask = float(primary.get("mask_area") if primary.get("mask_area") is not None else 0)
            if not (mask > 0):
                errs.append("mask_area_not_positive")
        except (TypeError, ValueError):
            errs.append("mask_area_invalid")
        try:
            score = float(primary.get("sam2_score", primary.get("score", float("nan"))))
            if not (score == score and abs(score) != float("inf")):
                errs.append("sam2_score_not_finite")
        except (TypeError, ValueError):
            errs.append("sam2_score_invalid")

    return errs


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V0-B4 formal legacy gateway replay")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--frame", type=Path, action="append", dest="frames", required=True)
    p.add_argument("--artifact-manifest", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--wait-timeout-s", type=float, default=600.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out: Path = args.output_dir
    if out.exists():
        print(f"ERROR: output directory already exists: {out}", file=sys.stderr)
        return 2
    if len(args.frames) != 2:
        print("ERROR: exactly two --frame paths required", file=sys.stderr)
        return 2

    shas = load_artifact_shas(args.artifact_manifest)
    for fp in args.frames:
        if fp.name not in shas:
            print(f"ERROR: {fp.name} missing from artifact manifest", file=sys.stderr)
            return 2
        if sha256_file(fp) != shas[fp.name]:
            print(f"ERROR: SHA mismatch for {fp}", file=sys.stderr)
            return 2

    vlm_base = os.environ.get("GMROBOT_VLM_BASE_URL", "").strip()
    perc_base = os.environ.get("GMROBOT_PERCEPTION_BASE_URL", "").strip()
    if args.execute and (not vlm_base or not perc_base):
        print("ERROR: GMROBOT_VLM_BASE_URL and GMROBOT_PERCEPTION_BASE_URL required", file=sys.stderr)
        return 2

    import yaml

    cfg_path = args.config if args.config.is_absolute() else (Path.cwd() / args.config)
    with cfg_path.open(encoding="utf-8") as f:
        shadow_cfg = yaml.safe_load(f) or {}
    if str(shadow_cfg.get("enforcement_mode", "shadow")).lower() != "shadow":
        print("ERROR: enforcement_mode must be shadow", file=sys.stderr)
        return 2
    if str(shadow_cfg.get("contract_mode", "")).lower() != "legacy_v2":
        print("ERROR: config contract_mode must be legacy_v2", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=False)
    stdout_path = out / "stdout.txt"
    stderr_path = out / "stderr.txt"
    # tee-like simple capture via redirect in shell; also write markers here
    stdout_path.write_text("")
    stderr_path.write_text("")

    input_manifest = {
        "frames": [
            {"path": str(args.frames[0]), "sha256": shas[args.frames[0].name], "sim_step": 0},
            {"path": str(args.frames[1]), "sha256": shas[args.frames[1].name], "sim_step": 10},
        ],
        "config": str(cfg_path),
        "contract_mode": "legacy_v2",
        "enforcement_mode": "shadow",
        "max_posts": MAX_POSTS,
        "execute": bool(args.execute),
        "vlm_alias": "vlm_endpoint",
        "perception_alias": "perception_endpoint",
        "safe_authorities": {"vlm": "http://127.0.0.1:18080", "perception": "http://127.0.0.1:18082"},
        "negative_sample_scene": True,
        "created_at": utc_now(),
    }
    (out / "input_manifest.json").write_text(json.dumps(input_manifest, indent=2) + "\n")

    if not args.execute:
        plan = {
            "mode": "dry-run",
            "planned_posts": [
                "vlm_analyze",
                "ground",
                "track_init",
                "vlm_analyze",
                "ground",
                "track_step",
            ],
            "max_posts": MAX_POSTS,
        }
        (out / "replay_summary.json").write_text(
            json.dumps({"verdict": "DRY_RUN", "posts": 0, "plan": plan}, indent=2) + "\n"
        )
        print("dry_run_ok")
        return 0

    ledger_path = out / "request_ledger.jsonl"
    budget = RequestBudget.create(ledger_path)
    ctx: dict[str, str] = {"request_id": "", "frame_id": "", "image_sha256": ""}

    # Resolve client yamls relative to GMRobot root
    vlm_yaml = ROOT / str(shadow_cfg.get("vlm_config") or "configs/vlm_client_legacy_gateway.yaml")
    perc_yaml = ROOT / str(
        shadow_cfg.get("perception_config") or "configs/perception_client_legacy_gateway.yaml"
    )
    vlm = VLMClient.from_yaml(str(vlm_yaml))
    perc = PerceptionClient.from_yaml(str(perc_yaml))
    vlm.config.base_url = vlm_base
    perc.config.base_url = perc_base
    if vlm.config.contract_mode != "legacy_v2" or perc.config.contract_mode != "legacy_v2":
        print("ERROR: clients must be legacy_v2", file=sys.stderr)
        return 2

    wrap_client_http(vlm, budget, get_context=lambda: ctx)
    wrap_client_http(perc, budget, get_context=lambda: ctx)

    log_dir = out / "shadow_logs"
    logger = FiveStageShadowLogger(str(log_dir), episode_id="v0b4", enabled=True)
    worker = FiveStageShadowWorker(
        vlm_analyze=lambda rgb, **kw: vlm.analyze(rgb, **kw),
        perception_ground=lambda rgb, **kw: perc.ground(rgb, **kw),
        perception_track=lambda rgb, **kw: perc.legacy_track_callback(rgb, **kw),
        queue_size=1,
        max_result_age_s=float(shadow_cfg.get("max_result_age_s", 2.0) or 2.0),
        enforcement_mode="shadow",
    )
    worker.start()

    verdict = "FORMAL_GATEWAY_REPLAY_PASS"
    frame_results: list[dict[str, Any]] = []
    prev_track_id = None
    submit_ms_list: list[float] = []
    try:
        for i, (fp, step) in enumerate(zip(args.frames, (0, 10))):
            request_id = str(uuid.uuid4())
            frame_id = str(uuid.uuid4())
            ctx["request_id"] = request_id
            ctx["frame_id"] = frame_id
            ctx["image_sha256"] = shas[fp.name]
            rgb = load_rgb(fp)

            t_sub = time.perf_counter()
            sub = worker.submit(
                rgb,
                sim_step=step,
                episode_id="v0b4",
                request_id=request_id,
                frame_id=frame_id,
            )
            submit_ms = (time.perf_counter() - t_sub) * 1000.0
            submit_ms_list.append(submit_ms)
            if not sub.get("accepted"):
                verdict = "VLM_FAIL"
                break
            if int(sub.get("dropped_to_enqueue") or 0) != 0:
                verdict = "CONTROL_LEAKAGE"
                break

            result = wait_for_result(worker, request_id=request_id, timeout_s=float(args.wait_timeout_s))
            logger.record(result)
            errs = validate_frame(
                result,
                frame_idx=i,
                expected_request_id=request_id,
                expected_frame_id=frame_id,
                prev_track_id=prev_track_id,
            )
            # leakage check each frame
            leak = result.get("leakage") or {}
            if any(int(leak.get(k, 0) or 0) != 0 for k in leak):
                verdict = "CONTROL_LEAKAGE"
                errs.append("leakage_nonzero")

            frame_payload = {
                "frame_index": i,
                "sim_step": step,
                "image_name": fp.name,
                "image_sha256": shas[fp.name],
                "submit_ms": submit_ms,
                "validation_errors": errs,
                "result": redact(result),
            }
            name = "frame_000000_result.json" if i == 0 else "frame_000010_result.json"
            (out / name).write_text(json.dumps(frame_payload, indent=2, ensure_ascii=False) + "\n")
            frame_results.append(frame_payload)

            if errs:
                verdict = classify_failure(i, result) or "GROUND_FAIL"
                break
            prev_track_id = result.get("track_id")

        # Final global checks
        if verdict == "FORMAL_GATEWAY_REPLAY_PASS":
            if budget._count != 6:
                verdict = "BUDGET_VIOLATION"
            if worker.metrics.dropped_frames != 0:
                verdict = "CONTROL_LEAKAGE"
            try:
                worker.assert_no_control_side_effects()
            except AssertionError:
                verdict = "CONTROL_LEAKAGE"

    except BudgetError as exc:
        verdict = "BUDGET_VIOLATION"
        (out / "fatal_error.json").write_text(json.dumps({"error": str(exc)}, indent=2) + "\n")
    except Exception as exc:  # noqa: BLE001
        if verdict == "FORMAL_GATEWAY_REPLAY_PASS":
            verdict = classify_failure(len(frame_results), None) or "VLM_FAIL"
        (out / "fatal_error.json").write_text(
            json.dumps({"error": str(exc), "type": type(exc).__name__}, indent=2) + "\n"
        )
    finally:
        worker.stop(timeout_s=5.0)
        logger.flush_summary(
            {
                "verdict": verdict,
                "post_count": budget._count,
                "stage_counts": dict(budget._stage_counts),
            }
        )
        logger.close()

    # Promote logger artifacts to required names
    if logger.session_dir and logger.session_dir.exists():
        for src_name, dst_name in (
            ("five_stage_shadow_requests.jsonl", "five_stage_shadow_requests.jsonl"),
            ("five_stage_shadow_steps.csv", "five_stage_shadow_steps.csv"),
            ("five_stage_shadow_summary.json", "five_stage_shadow_summary.json"),
        ):
            src = logger.session_dir / src_name
            if src.exists():
                shutil.copy2(src, out / dst_name)

    summary = {
        "verdict": verdict,
        "post_count": budget._count,
        "stage_counts": dict(budget._stage_counts),
        "post_order": [h.get("endpoint_alias") for h in budget.history if h.get("status") == "planned"],
        "submit_ms": submit_ms_list,
        "dropped_frames": worker.metrics.dropped_frames,
        "stale_result_count": worker.metrics.stale_result_count,
        "leakage": worker.leakage.as_dict(),
        "retries": 0,
        "credentials_read": False,
        "tunnel_modified": False,
        "remote_modified": False,
        "isaac_run": False,
        "negative_sample_scene": True,
        "human_tool_ppe_validated": False,
        "paper_five_stage_complete": False,
        "track_state_native": False,
        "id_source": "local_gateway",
        "frames_completed": len(frame_results),
        "completed_at": utc_now(),
    }
    # Attach per-frame quick stats
    summary["frames"] = []
    for fr in frame_results:
        r = fr.get("result") or {}
        summary["frames"].append(
            {
                "sim_step": fr.get("sim_step"),
                "keywords": r.get("keywords"),
                "detection_count": len(((r.get("ground") or {}).get("detections") or [])),
                "track_state": r.get("track_state"),
                "track_id": r.get("track_id"),
                "vlm_latency_ms": r.get("vlm_latency_ms"),
                "ground_latency_ms": r.get("ground_latency_ms"),
                "track_latency_ms": r.get("track_latency_ms"),
                "end_to_end_latency_ms": r.get("end_to_end_latency_ms"),
                "queue_wait_ms": r.get("queue_wait_ms"),
                "validation_errors": fr.get("validation_errors"),
            }
        )
    (out / "replay_summary.json").write_text(json.dumps(redact(summary), indent=2) + "\n")
    print(f"replay_verdict={verdict} posts={budget._count}")
    return 0 if verdict == "FORMAL_GATEWAY_REPLAY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
