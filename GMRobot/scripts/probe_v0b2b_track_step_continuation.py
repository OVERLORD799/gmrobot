#!/usr/bin/env python3
"""V0-B2B single track-step continuation against an existing remote session.

Default dry-run. ``--execute`` allows exactly one POST /track action=step.
Never re-runs VLM/ground/track init. Never creates a new session.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import urllib.error
    import urllib.request
except ImportError:  # pragma: no cover
    urllib = None  # type: ignore

MAX_POSTS = 1
ENDPOINT_ALIAS = "track_step_continuation"
TIMEOUT_S = 180.0
EXPECTED_TRACK_ID = 0
FRAME_INDEX = 10


class ContinuationError(RuntimeError):
    pass


class ContinuationBudgetError(ContinuationError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def is_valid_track_id(track_id: Any) -> bool:
    """track_id=0 is valid. Never use bool(track_id)."""
    if track_id is None:
        return False
    if isinstance(track_id, bool):  # reject True/False masquerading
        return False
    if isinstance(track_id, int):
        return True
    if isinstance(track_id, float) and track_id == int(track_id):
        return True
    if isinstance(track_id, str) and track_id.strip() != "":
        return True
    return False


def track_id_equals(track_id: Any, expected: Any) -> bool:
    if not is_valid_track_id(track_id):
        return False
    try:
        return int(track_id) == int(expected)
    except (TypeError, ValueError):
        return str(track_id) == str(expected)


def redact_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {"image_b64", "imageb64"}:
                out[k] = "<redacted>"
            elif lk == "session_id":
                out[k] = "<redacted>"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [redact_secrets(x) for x in obj]
    return obj


def load_session_id_from_parent(parent_init_path: Path) -> str:
    data = json.loads(parent_init_path.read_text())
    resp = data.get("response") if isinstance(data, dict) else None
    if not isinstance(resp, dict):
        raise ContinuationError("parent track_init_response missing response object")
    sid = resp.get("session_id")
    if not isinstance(sid, str) or not sid.strip():
        raise ContinuationError("parent session_id missing")
    return sid


@dataclass
class ContinuationLedger:
    path: Path
    _count: int = 0

    @classmethod
    def reject_if_exists(cls, path: Path) -> None:
        if path.exists():
            raise ContinuationError(f"ledger already exists (refuse overwrite): {path}")

    @classmethod
    def create_fresh(cls, path: Path) -> "ContinuationLedger":
        cls.reject_if_exists(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=False)
        return cls(path=path)

    @property
    def post_count(self) -> int:
        return self._count

    def _append(self, record: dict[str, Any]) -> None:
        # Hard rule: never persist session_id or image_b64
        safe = {k: v for k, v in record.items() if k not in {"session_id", "image_b64"}}
        if "session_id" in json.dumps(safe):
            raise ContinuationError("refusing to write session_id into ledger")
        line = json.dumps(safe, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def plan(self, *, image_sha256: str, expected_track_id: int = EXPECTED_TRACK_ID) -> int:
        if self._count >= MAX_POSTS:
            raise ContinuationBudgetError(f"continuation POST budget exhausted ({MAX_POSTS})")
        request_index = self._count + 1
        self._append(
            {
                "request_index": request_index,
                "endpoint_alias": ENDPOINT_ALIAS,
                "image_sha256": image_sha256,
                "expected_track_id": expected_track_id,
                "planned_at": utc_now(),
                "status": "planned",
            }
        )
        self._count += 1
        return request_index

    def finalize(
        self,
        *,
        request_index: int,
        status: str,
        http_status: int | None = None,
        elapsed_s: float | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"completed", "failed", "timeout"}:
            raise ContinuationError(f"invalid status={status}")
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


HttpPostFn = Callable[[str, dict[str, Any], float], tuple[int, Any, float, str | None]]


def default_http_post(url: str, payload: dict[str, Any], timeout_s: float) -> tuple[int, Any, float, str | None]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            elapsed = time.perf_counter() - t0
            text = raw.decode("utf-8", errors="replace")
            try:
                body: Any = json.loads(text)
            except json.JSONDecodeError:
                body = text[:2048]
            return int(resp.status), body, elapsed, None
    except TimeoutError:
        return 0, None, time.perf_counter() - t0, "timeout"
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - t0
        raw = exc.read() if hasattr(exc, "read") else b""
        text = raw.decode("utf-8", errors="replace") if raw else str(exc)
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text[:2048]
        return int(exc.code), body, elapsed, None
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        msg = str(exc).lower()
        kind = "timeout" if "timed out" in msg or "timeout" in msg else "http_error"
        return 0, str(exc)[:2048], elapsed, kind


@dataclass
class ContinuationContext:
    output_dir: Path
    execute: bool
    perception_base: str
    parent_init_path: Path
    step_image: Path
    image_sha256: str
    expected_track_id: int = EXPECTED_TRACK_ID
    frame_index: int = FRAME_INDEX
    http_post: HttpPostFn = field(default=default_http_post)
    verdict: str | None = None
    posts: int = 0


def classify_and_validate(
    *,
    http_status: int,
    err_kind: str | None,
    body: Any,
    expected_session: str,
    expected_track_id: int,
    expected_frame_index: int,
) -> dict[str, Any]:
    if err_kind == "timeout":
        return {"verdict": "TRACK_STEP_TIMEOUT", "pass": False, "session_match": False}

    if http_status in {404, 410, 422} or (
        isinstance(body, dict)
        and any(tok in json.dumps(body).lower() for tok in ("expired", "unknown session", "session not found", "invalid session"))
    ):
        # Prefer SESSION_EXPIRED when body indicates it; else HTTP fail
        blob = json.dumps(body).lower() if body is not None else ""
        if any(tok in blob for tok in ("expired", "unknown session", "session not found", "invalid session")):
            return {"verdict": "SESSION_EXPIRED", "pass": False, "session_match": False}

    if http_status != 200:
        if http_status in {404, 410}:
            return {"verdict": "SESSION_EXPIRED", "pass": False, "session_match": False}
        return {"verdict": "TRACK_STEP_HTTP_FAIL", "pass": False, "session_match": False, "http_status": http_status}

    if not isinstance(body, dict):
        return {"verdict": "TRACK_STEP_SCHEMA_FAIL", "pass": False, "session_match": False, "errors": ["response_not_json_object"]}

    sid = body.get("session_id")
    session_match = isinstance(sid, str) and sid == expected_session
    errors: list[str] = []
    if not session_match:
        errors.append("session_mismatch_or_missing")

    tracks = body.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        errors.append("tracks_empty_or_missing")

    associated = None
    if isinstance(tracks, list):
        for t in tracks:
            if isinstance(t, dict) and track_id_equals(t.get("track_id"), expected_track_id):
                associated = t
                break
    if associated is None:
        return {
            "verdict": "TRACK_ID_MISSING",
            "pass": False,
            "session_match": session_match,
            "errors": errors + ["track_id_not_found"],
        }

    box = associated.get("box_xyxy")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        errors.append("box_xyxy_invalid")
    else:
        try:
            [float(x) for x in box]
        except (TypeError, ValueError):
            errors.append("box_xyxy_not_numeric")

    try:
        mask_area = float(associated.get("mask_area"))
        if not (mask_area > 0):
            errors.append("mask_area_not_positive")
    except (TypeError, ValueError):
        errors.append("mask_area_invalid")
        mask_area = None

    try:
        score = float(associated.get("sam2_score", associated.get("score")))
        if not (score == score and abs(score) != float("inf")):  # finite
            errors.append("sam2_score_not_finite")
    except (TypeError, ValueError):
        errors.append("sam2_score_invalid")
        score = None

    frame_index = body.get("frame_index")
    if frame_index != expected_frame_index:
        errors.append(f"frame_index_mismatch:{frame_index!r}")

    track_state_native = "track_state" in body or "track_state" in associated

    if errors:
        # session mismatch alone with otherwise ok fields still schema/session issue
        verdict = "SESSION_EXPIRED" if "session_mismatch_or_missing" in errors and http_status == 200 else "TRACK_STEP_SCHEMA_FAIL"
        if "session_mismatch_or_missing" in errors and not any(
            e.startswith("box_") or e.startswith("mask_") or e.startswith("sam2_") or e.startswith("frame_") for e in errors
        ):
            # only session issue on 200 — treat as expired/wrong session
            verdict = "SESSION_EXPIRED"
        return {
            "verdict": verdict,
            "pass": False,
            "session_match": session_match,
            "errors": errors,
            "track_state_native": track_state_native,
        }

    return {
        "verdict": "LEGACY_GATEWAY_FEASIBLE_COMPOSITE",
        "pass": True,
        "session_match": True,
        "track_id_associated": True,
        "track_id": expected_track_id,
        "box_xyxy": [float(x) for x in box],
        "mask_area": mask_area,
        "sam2_score": score,
        "velocity_xy_px_s": associated.get("velocity_xy_px_s"),
        "speed_px_s": associated.get("speed_px_s"),
        "direction_deg": associated.get("direction_deg"),
        "re_detected": body.get("re_detected"),
        "frame_index": frame_index,
        "track_state_native": False if not track_state_native else True,
        "errors": [],
    }


def run_continuation(ctx: ContinuationContext) -> int:
    if ctx.output_dir.exists() and any(ctx.output_dir.iterdir()):
        raise ContinuationError(f"output directory already exists/non-empty: {ctx.output_dir}")

    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ctx.output_dir / "request_ledger.jsonl"
    ContinuationLedger.reject_if_exists(ledger_path)

    # Load session in memory only — never print
    try:
        session_id = load_session_id_from_parent(ctx.parent_init_path)
    except ContinuationError:
        # Zero POST if session missing
        summary = {
            "verdict": "SESSION_EXPIRED",
            "pass": False,
            "posts": 0,
            "session_match": False,
            "reason": "parent_session_missing",
            "note": "zero POST because session could not be loaded",
        }
        (ctx.output_dir / "continuation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        ctx.verdict = "SESSION_EXPIRED"
        return 1

    if not ctx.execute:
        plan = {
            "mode": "dry-run",
            "posts": 0,
            "max_posts": MAX_POSTS,
            "endpoint_alias": ENDPOINT_ALIAS,
            "frame_index": ctx.frame_index,
            "expected_track_id": ctx.expected_track_id,
            "image_sha256": ctx.image_sha256,
            "session_loaded": True,
            "ledger_created": False,
        }
        (ctx.output_dir / "continuation_summary.json").write_text(json.dumps(plan, indent=2) + "\n")
        ctx.verdict = "DRY_RUN"
        return 0

    ledger = ContinuationLedger.create_fresh(ledger_path)
    idx = ledger.plan(image_sha256=ctx.image_sha256, expected_track_id=ctx.expected_track_id)

    image_b64 = load_image_b64(ctx.step_image)
    payload = {
        "action": "step",
        "session_id": session_id,
        "frame_index": ctx.frame_index,
        "image_b64": image_b64,
        "meta": {
            "probe": "v0b2b_track_step_continuation",
            "parent_probe": "v0b2b_legacy_probe_20260721",
            "expected_track_id": ctx.expected_track_id,
            "image_sha256": ctx.image_sha256,
        },
    }

    request_summary = {
        "request_index": idx,
        "endpoint_alias": ENDPOINT_ALIAS,
        "url_path": "/track",
        "action": "step",
        "frame_index": ctx.frame_index,
        "expected_track_id": ctx.expected_track_id,
        "image_sha256": ctx.image_sha256,
        "timeout_s": TIMEOUT_S,
        "session_id": "<redacted>",
        "image_b64": "<redacted>",
        "meta": payload["meta"],
    }
    (ctx.output_dir / "request_summary.json").write_text(
        json.dumps(request_summary, indent=2, ensure_ascii=False) + "\n"
    )

    http_status, body, elapsed, err_kind = ctx.http_post(
        f"{ctx.perception_base.rstrip('/')}/track", payload, TIMEOUT_S
    )
    ctx.posts = 1

    if err_kind == "timeout":
        ledger.finalize(request_index=idx, status="timeout", http_status=http_status, elapsed_s=elapsed, error="timeout")
    elif http_status == 200:
        ledger.finalize(request_index=idx, status="completed", http_status=http_status, elapsed_s=elapsed)
    else:
        ledger.finalize(
            request_index=idx,
            status="failed",
            http_status=http_status,
            elapsed_s=elapsed,
            error=err_kind or f"http_{http_status}",
        )

    # Persist response with session_id redacted in on-disk summary companion;
    # keep structural fields. Full body redacts session_id + any b64.
    saved = {
        "http_status": http_status,
        "elapsed_s": elapsed,
        "error_kind": err_kind,
        "response": redact_secrets(body) if body is not None else None,
    }
    (ctx.output_dir / "track_step_response.json").write_text(
        json.dumps(saved, indent=2, ensure_ascii=False) + "\n"
    )

    result = classify_and_validate(
        http_status=http_status,
        err_kind=err_kind,
        body=body,
        expected_session=session_id,
        expected_track_id=ctx.expected_track_id,
        expected_frame_index=ctx.frame_index,
    )
    ctx.verdict = str(result["verdict"])

    summary = {
        "verdict": ctx.verdict,
        "pass": bool(result.get("pass")),
        "posts": 1,
        "retries": 0,
        "http_status": http_status,
        "elapsed_s": elapsed,
        "session_match": bool(result.get("session_match")),
        "track_id_associated": bool(result.get("track_id_associated", False)),
        "expected_track_id": ctx.expected_track_id,
        "box_xyxy": result.get("box_xyxy"),
        "mask_area": result.get("mask_area"),
        "sam2_score": result.get("sam2_score"),
        "velocity_xy_px_s": result.get("velocity_xy_px_s"),
        "speed_px_s": result.get("speed_px_s"),
        "direction_deg": result.get("direction_deg"),
        "re_detected": result.get("re_detected"),
        "frame_index": result.get("frame_index", ctx.frame_index),
        "track_state_native": result.get("track_state_native", False),
        "errors": result.get("errors"),
        "composite": {
            "vlm_ground_init_source": "v0b2b_legacy_probe_20260721",
            "step_source": "v0b2b_track_step_continuation_20260721",
            "same_session": bool(result.get("session_match")),
            "original_track_init_fail_was_local_audit_bug": True,
            "five_stage_paper_validated": False,
            "legacy_gateway_technically_feasible": ctx.verdict == "LEGACY_GATEWAY_FEASIBLE_COMPOSITE",
            "negative_sample_no_human_risk_semantics": True,
        },
        "credentials_read": False,
        "tunnel_modified": False,
        "remote_modified": False,
        "completed_at": utc_now(),
    }
    (ctx.output_dir / "continuation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    # Never print session_id
    print(f"continuation_verdict={ctx.verdict} posts={ctx.posts} session_match={summary['session_match']}")
    return 0 if summary["pass"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V0-B2B track-step continuation (max 1 POST)")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--parent-init-response", type=Path, required=True)
    p.add_argument("--step-image", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--expected-track-id", type=int, default=EXPECTED_TRACK_ID)
    p.add_argument("--frame-index", type=int, default=FRAME_INDEX)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = args.output_dir
    if out.exists():
        print(f"ERROR: output directory already exists: {out}", file=sys.stderr)
        return 2

    perc = os.environ.get("GMROBOT_PERCEPTION_BASE_URL", "").strip()
    if args.execute and not perc:
        print("ERROR: GMROBOT_PERCEPTION_BASE_URL required for --execute", file=sys.stderr)
        return 2

    if not args.step_image.is_file():
        print("ERROR: step image missing", file=sys.stderr)
        return 2
    if not args.parent_init_response.is_file():
        print("ERROR: parent init response missing", file=sys.stderr)
        return 2

    image_sha = sha256_file(args.step_image)
    ctx = ContinuationContext(
        output_dir=out,
        execute=bool(args.execute),
        perception_base=perc or "http://127.0.0.1:18082",
        parent_init_path=args.parent_init_response,
        step_image=args.step_image,
        image_sha256=image_sha,
        expected_track_id=int(args.expected_track_id),
        frame_index=int(args.frame_index),
    )
    try:
        return run_continuation(ctx)
    except ContinuationError as exc:
        # Do not include session ids in error prints if present
        msg = str(exc)
        print(f"ERROR: {msg}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
