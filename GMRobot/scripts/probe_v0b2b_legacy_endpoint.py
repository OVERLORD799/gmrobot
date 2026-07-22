#!/usr/bin/env python3
"""V0-B2B legacy remote endpoint capability probe (hard-capped POSTs).

Default is dry-run. Real POSTs require explicit ``--execute``.
Maximum 4 POSTs total (vlm / ground / track_init / track_step), one each.
Timeouts consume budget and must not be retried.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import urllib.error
    import urllib.request
except ImportError:  # pragma: no cover
    urllib = None  # type: ignore

MAX_POSTS = 4
ENDPOINT_ALIASES = ("vlm_analyze", "ground", "track_init", "track_step")
VLM_TIMEOUT_S = 180.0
GROUND_TIMEOUT_S = 300.0
TRACK_TIMEOUT_S = 300.0

RISK_TYPES = frozenset({"static", "dynamic", "functional", "none"})
SUGGESTED_ACTIONS = frozenset({"continue", "slow_down", "stop", "replan", "alert"})
SPATIAL_HINTS = frozenset({"left", "right", "above", "retreat", "none"})
REQUIRED_VLM_FIELDS = (
    "scene_summary",
    "keywords",
    "risk_type",
    "risk_confidence",
    "affected_entities",
    "predicted_consequence",
    "prediction_horizon_s",
    "explanation",
    "suggested_action",
    "spatial_hint",
)

STRICT_VLM_PROMPT = """Analyze robot workspace human-safety risks from the image.
Reply with ONLY a single JSON object (no markdown, no prose) with exactly these keys:
{
  "scene_summary": "...",
  "keywords": ["..."],
  "risk_type": "static|dynamic|functional|none",
  "risk_confidence": 0.0,
  "affected_entities": ["..."],
  "predicted_consequence": "...",
  "prediction_horizon_s": 1.5,
  "explanation": "...",
  "suggested_action": "continue|slow_down|stop|replan|alert",
  "spatial_hint": "left|right|above|retreat|none"
}
Do not invent legacy fields. Do not wrap the JSON in code fences."""


class ProbeError(RuntimeError):
    """Fatal probe error (budget, ledger, or precheck)."""


class ProbeBudgetError(ProbeError):
    """POST budget exceeded or endpoint reused."""


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


def redact_for_log(obj: Any) -> Any:
    """Recursively drop image_b64 and truncate huge strings."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.lower() in {"image_b64", "imageb64", "image"}:
                out[k] = "<redacted>"
            else:
                out[k] = redact_for_log(v)
        return out
    if isinstance(obj, list):
        return [redact_for_log(x) for x in obj]
    if isinstance(obj, str) and len(obj) > 4096:
        return obj[:4096] + f"...<truncated len={len(obj)}>"
    return obj


def normalize_keywords(keywords: Any) -> list[str]:
    if keywords is None:
        return []
    if isinstance(keywords, str):
        items = [keywords]
    elif isinstance(keywords, (list, tuple)):
        items = list(keywords)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def keywords_to_text_prompt(keywords: list[str]) -> str:
    return " . ".join(keywords)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract first JSON object from model text. No legacy field synthesis."""
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    # Strip common fences if present (still require parseable JSON body)
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Find first balanced {...}
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    return None
                break
    return None


def validate_vlm_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate target five-stage JSON only. Do not use legacy vlm_* fillers."""
    errors: list[str] = []
    for key in REQUIRED_VLM_FIELDS:
        if key not in payload:
            errors.append(f"missing:{key}")
    if errors:
        return {"pass": False, "errors": errors, "parsed": payload}

    risk_type = str(payload.get("risk_type", ""))
    if risk_type not in RISK_TYPES:
        errors.append(f"invalid_risk_type:{risk_type!r}")

    action = str(payload.get("suggested_action", ""))
    if action not in SUGGESTED_ACTIONS:
        errors.append(f"invalid_suggested_action:{action!r}")

    hint = str(payload.get("spatial_hint", ""))
    if hint not in SPATIAL_HINTS:
        errors.append(f"invalid_spatial_hint:{hint!r}")

    try:
        conf = float(payload["risk_confidence"])
        if not (0.0 <= conf <= 1.0):
            errors.append(f"risk_confidence_out_of_range:{conf}")
    except (TypeError, ValueError):
        errors.append("risk_confidence_not_float")

    kws = payload.get("keywords")
    if not isinstance(kws, list) or not kws or not all(isinstance(x, str) and x.strip() for x in kws):
        errors.append("keywords_must_be_nonempty_string_list")

    entities = payload.get("affected_entities")
    if not isinstance(entities, list):
        errors.append("affected_entities_must_be_list")

    consequence = str(payload.get("predicted_consequence", "")).strip()
    if not consequence:
        errors.append("predicted_consequence_empty")

    try:
        horizon = float(payload["prediction_horizon_s"])
        if not (horizon > 0):
            errors.append(f"prediction_horizon_s_not_positive:{horizon}")
    except (TypeError, ValueError):
        errors.append("prediction_horizon_s_not_float")

    for text_key in ("scene_summary", "explanation"):
        if not str(payload.get(text_key, "")).strip():
            errors.append(f"{text_key}_empty")

    return {"pass": len(errors) == 0, "errors": errors, "parsed": payload}


def is_fake_model_id(value: Any) -> bool:
    s = str(value or "").strip().lower()
    if not s:
        return True
    return any(tok in s for tok in ("fake", "mock", "test"))


def load_artifact_sha_map(manifest_path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with manifest_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rel = str(rec.get("image_path", ""))
            mapping[rel] = str(rec["sha256"])
            mapping[Path(rel).name] = str(rec["sha256"])
    return mapping


def verify_frame_sha(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise ProbeError(f"SHA mismatch for {path}: expected={expected} actual={actual}")


@dataclass
class Ledger:
    path: Path
    _count: int = 0
    _aliases_used: set[str] = field(default_factory=set)
    _entries: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create_fresh(cls, path: Path) -> "Ledger":
        if path.exists():
            raise ProbeError(f"ledger already exists (refuse re-run): {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Create empty file so subsequent creates fail if race
        path.touch(exist_ok=False)
        return cls(path=path)

    @classmethod
    def reject_if_exists(cls, path: Path) -> None:
        if path.exists():
            raise ProbeError(f"ledger already exists (refuse re-run): {path}")

    @property
    def post_count(self) -> int:
        return self._count

    def _append_line(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        self._entries.append(record)

    def plan(
        self,
        *,
        endpoint_alias: str,
        request_id: str,
        frame_id: str,
        image_sha256: str,
    ) -> int:
        if endpoint_alias not in ENDPOINT_ALIASES:
            raise ProbeBudgetError(f"unknown endpoint_alias={endpoint_alias}")
        if endpoint_alias in self._aliases_used:
            raise ProbeBudgetError(f"endpoint already used: {endpoint_alias}")
        if self._count >= MAX_POSTS:
            raise ProbeBudgetError(f"POST budget exhausted ({MAX_POSTS})")
        request_index = self._count + 1
        rec = {
            "request_index": request_index,
            "endpoint_alias": endpoint_alias,
            "request_id": request_id,
            "frame_id": frame_id,
            "image_sha256": image_sha256,
            "planned_at": utc_now(),
            "status": "planned",
        }
        self._append_line(rec)
        self._aliases_used.add(endpoint_alias)
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
        extra: dict[str, Any] | None = None,
    ) -> None:
        if status not in {"completed", "failed", "timeout"}:
            raise ProbeError(f"invalid finalize status={status}")
        rec: dict[str, Any] = {
            "request_index": request_index,
            "status": status,
            "finalized_at": utc_now(),
            "http_status": http_status,
            "elapsed_s": elapsed_s,
            "error": error,
        }
        if extra:
            rec["extra"] = redact_for_log(extra)
        self._append_line(rec)


HttpPostFn = Callable[[str, dict[str, Any], float], tuple[int, Any, float, str | None]]


def default_http_post(url: str, payload: dict[str, Any], timeout_s: float) -> tuple[int, Any, float, str | None]:
    """Return (http_status, parsed_or_text, elapsed_s, error_kind).

    error_kind is 'timeout' | 'http_error' | None.
    Never retries.
    """
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
            status = int(resp.status)
            text = raw.decode("utf-8", errors="replace")
            try:
                body: Any = json.loads(text)
            except json.JSONDecodeError:
                body = text[:2048]
            return status, body, elapsed, None
    except TimeoutError:
        elapsed = time.perf_counter() - t0
        return 0, None, elapsed, "timeout"
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - t0
        raw = exc.read() if hasattr(exc, "read") else b""
        text = raw.decode("utf-8", errors="replace") if raw else str(exc)
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text[:2048]
        return int(exc.code), body, elapsed, None
    except Exception as exc:  # noqa: BLE001 — probe records and stops
        # urllib raises URLError with reason often containing timeout
        elapsed = time.perf_counter() - t0
        msg = str(exc).lower()
        kind = "timeout" if "timed out" in msg or "timeout" in msg else "http_error"
        return 0, str(exc)[:2048], elapsed, kind


@dataclass
class ProbeContext:
    output_dir: Path
    execute: bool
    vlm_base: str
    perception_base: str
    vlm_image: Path
    track_image: Path
    vlm_sha: str
    track_sha: str
    box_threshold: float = 0.2
    text_threshold: float = 0.25
    max_detections: int = 10
    http_post: HttpPostFn = field(default=default_http_post)
    ledger: Ledger | None = None
    posts_executed: list[str] = field(default_factory=list)
    verdict: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def write_json(self, name: str, obj: Any) -> None:
        path = self.output_dir / name
        path.write_text(json.dumps(redact_for_log(obj), indent=2, ensure_ascii=False) + "\n")


def select_detection(detections: list[dict[str, Any]], keywords: list[str]) -> dict[str, Any] | None:
    """Prefer keyword-matching label, then highest score; require box_xyxy."""
    valid: list[dict[str, Any]] = []
    for d in detections:
        if not isinstance(d, dict):
            continue
        box = d.get("box_xyxy")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            [float(x) for x in box]
        except (TypeError, ValueError):
            continue
        valid.append(d)
    if not valid:
        return None
    kw_lower = {k.lower() for k in keywords}

    def score_of(d: dict[str, Any]) -> float:
        try:
            return float(d.get("score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    matched = [d for d in valid if str(d.get("label", "")).strip().lower() in kw_lower
               or any(k in str(d.get("label", "")).lower() for k in kw_lower)]
    pool = matched if matched else valid
    pool_sorted = sorted(pool, key=score_of, reverse=True)
    chosen = pool_sorted[0]
    return {
        "detection": chosen,
        "selection_rule": "keyword_match_then_highest_score" if matched else "highest_score_only",
        "keyword_matched": bool(matched),
        "candidates_valid": len(valid),
        "candidates_keyword_matched": len(matched),
    }


def run_probe(ctx: ProbeContext) -> int:
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ctx.output_dir / "request_ledger.jsonl"
    Ledger.reject_if_exists(ledger_path)

    input_manifest = {
        "vlm_image": str(ctx.vlm_image),
        "track_image": str(ctx.track_image),
        "vlm_sha256": ctx.vlm_sha,
        "track_sha256": ctx.track_sha,
        "vlm_endpoint_alias": "vlm_endpoint",
        "perception_endpoint_alias": "perception_endpoint",
        "vlm_safe_authority": "http://127.0.0.1:18080",
        "perception_safe_authority": "http://127.0.0.1:18082",
        "execute": ctx.execute,
        "created_at": utc_now(),
        "note": "negative-sample scene RGB; not hand/PPE/tool semantic validation",
    }
    ctx.write_json("input_manifest.json", input_manifest)

    if not ctx.execute:
        plan = {
            "mode": "dry-run",
            "planned_posts": [
                {"index": 1, "alias": "vlm_analyze", "path": "/analyze", "image": "vlm"},
                {"index": 2, "alias": "ground", "path": "/ground", "image": "vlm", "depends": "vlm_pass"},
                {"index": 3, "alias": "track_init", "path": "/track action=init", "image": "vlm", "depends": "ground_nonempty"},
                {"index": 4, "alias": "track_step", "path": "/track action=step", "image": "track", "depends": "track_init_pass"},
            ],
            "max_posts": MAX_POSTS,
            "ledger_created": False,
        }
        ctx.write_json("dry_run_plan.json", plan)
        ctx.verdict = "DRY_RUN"
        ctx.summary = {"verdict": "DRY_RUN", "post_count": 0, "posts_executed": []}
        ctx.write_json("probe_summary.json", ctx.summary)
        return 0

    ctx.ledger = Ledger.create_fresh(ledger_path)
    assert ctx.ledger is not None

    # ---- POST 1: VLM ----
    vlm_request_id = str(uuid.uuid4())
    vlm_frame_id = str(uuid.uuid4())
    idx = ctx.ledger.plan(
        endpoint_alias="vlm_analyze",
        request_id=vlm_request_id,
        frame_id=vlm_frame_id,
        image_sha256=ctx.vlm_sha,
    )
    image_b64 = load_image_b64(ctx.vlm_image)
    vlm_body = {
        "image_b64": image_b64,
        "prompt": STRICT_VLM_PROMPT,
        "meta": {
            "local_request_id": vlm_request_id,
            "frame_id": vlm_frame_id,
            "image_sha256": ctx.vlm_sha,
            "schema_version": "five_stage_vlm_v1",
            "prompt_version": "five_stage_safety_v1",
            "probe": "v0b2b",
        },
    }
    ctx.write_json(
        "vlm_request_summary.json",
        {
            "request_index": idx,
            "endpoint_alias": "vlm_analyze",
            "url_path": "/analyze",
            "request_id": vlm_request_id,
            "frame_id": vlm_frame_id,
            "image_sha256": ctx.vlm_sha,
            "timeout_s": VLM_TIMEOUT_S,
            "meta": vlm_body["meta"],
            "prompt_chars": len(STRICT_VLM_PROMPT),
            "image_b64": "<redacted>",
        },
    )
    http_status, resp, elapsed, err_kind = ctx.http_post(
        f"{ctx.vlm_base.rstrip('/')}/analyze", vlm_body, VLM_TIMEOUT_S
    )
    ctx.posts_executed.append("vlm_analyze")
    if err_kind == "timeout":
        ctx.ledger.finalize(request_index=idx, status="timeout", http_status=http_status, elapsed_s=elapsed, error="timeout")
        ctx.write_json("vlm_response.json", {"error": "timeout", "elapsed_s": elapsed})
        ctx.verdict = "VLM_CAPABILITY_FAIL"
        return _finish(ctx, vlm_pass=False)

    ctx.ledger.finalize(
        request_index=idx,
        status="completed" if http_status == 200 else "failed",
        http_status=http_status,
        elapsed_s=elapsed,
        error=None if http_status == 200 else f"http_{http_status}",
    )
    ctx.write_json(
        "vlm_response.json",
        {
            "http_status": http_status,
            "elapsed_s": elapsed,
            "response": resp if isinstance(resp, dict) else {"raw_text_truncated": resp},
            "model_id_from_response": resp.get("model_id") if isinstance(resp, dict) else None,
        },
    )

    vlm_ok = False
    parsed = None
    validation: dict[str, Any] = {"pass": False, "errors": ["not_json_response"]}
    if http_status == 200 and isinstance(resp, dict):
        # Extract ONLY from text / explicit model output — never synthesize from vlm_* legacy
        text_field = resp.get("text")
        if not isinstance(text_field, str) or not text_field.strip():
            # Some services may put JSON in "detail" as string — only accept if clearly model text
            # Spec: from `text` or explicit model output field. Do not use vlm_risk_type.
            for alt in ("model_output", "output", "content"):
                if isinstance(resp.get(alt), str) and str(resp.get(alt)).strip():
                    text_field = resp[alt]
                    break
        parsed = extract_json_object(text_field) if isinstance(text_field, str) else None
        if parsed is None:
            validation = {
                "pass": False,
                "errors": ["could_not_extract_target_json_from_text"],
                "text_preview": (text_field[:500] if isinstance(text_field, str) else None),
                "legacy_vlm_fields_present": [k for k in resp if str(k).startswith("vlm_")],
                "note": "legacy vlm_* fields were NOT used to fill missing schema",
            }
        else:
            validation = validate_vlm_schema(parsed)
            validation["text_source"] = "text" if resp.get("text") == text_field else "alt_model_output"
            validation["legacy_vlm_fields_ignored"] = [k for k in resp if str(k).startswith("vlm_")]
        vlm_ok = bool(validation.get("pass"))
    else:
        validation = {
            "pass": False,
            "errors": [f"http_status_{http_status}" if http_status != 200 else "response_not_json"],
        }

    ctx.write_json("vlm_schema_validation.json", validation)
    if not vlm_ok:
        ctx.verdict = "VLM_CAPABILITY_FAIL"
        return _finish(ctx, vlm_pass=False, keywords=[], parsed_vlm=parsed, validation=validation)

    assert parsed is not None
    keywords = normalize_keywords(parsed["keywords"])
    text_prompt = keywords_to_text_prompt(keywords)

    # ---- POST 2: ground ----
    ground_request_id = str(uuid.uuid4())
    ground_frame_id = vlm_frame_id  # same frame
    idx2 = ctx.ledger.plan(
        endpoint_alias="ground",
        request_id=ground_request_id,
        frame_id=ground_frame_id,
        image_sha256=ctx.vlm_sha,
    )
    ground_body = {
        "image_b64": image_b64,
        "text_prompt": text_prompt,
        "run_sam2": True,
        "box_threshold": ctx.box_threshold,
        "text_threshold": ctx.text_threshold,
        "max_detections": ctx.max_detections,
        "meta": {
            "local_request_id": ground_request_id,
            "parent_vlm_request_id": vlm_request_id,
            "frame_id": ground_frame_id,
            "image_sha256": ctx.vlm_sha,
            "keywords": keywords,
            "probe": "v0b2b",
        },
    }
    ctx.write_json(
        "ground_request_summary.json",
        {
            "request_index": idx2,
            "endpoint_alias": "ground",
            "url_path": "/ground",
            "request_id": ground_request_id,
            "parent_vlm_request_id": vlm_request_id,
            "frame_id": ground_frame_id,
            "image_sha256": ctx.vlm_sha,
            "keywords": keywords,
            "text_prompt": text_prompt,
            "box_threshold": ctx.box_threshold,
            "text_threshold": ctx.text_threshold,
            "max_detections": ctx.max_detections,
            "timeout_s": GROUND_TIMEOUT_S,
            "image_b64": "<redacted>",
        },
    )
    http_status, resp, elapsed, err_kind = ctx.http_post(
        f"{ctx.perception_base.rstrip('/')}/ground", ground_body, GROUND_TIMEOUT_S
    )
    ctx.posts_executed.append("ground")
    if err_kind == "timeout" or http_status == 503:
        ctx.ledger.finalize(
            request_index=idx2,
            status="timeout" if err_kind == "timeout" else "failed",
            http_status=http_status,
            elapsed_s=elapsed,
            error=err_kind or f"http_{http_status}",
        )
        ctx.write_json("ground_response.json", {"http_status": http_status, "elapsed_s": elapsed, "response": resp, "error": err_kind})
        ctx.verdict = "PERCEPTION_BACKEND_NOT_READY"
        return _finish(ctx, vlm_pass=True, keywords=keywords, parsed_vlm=parsed, validation=validation)

    ctx.ledger.finalize(
        request_index=idx2,
        status="completed" if http_status == 200 else "failed",
        http_status=http_status,
        elapsed_s=elapsed,
        error=None if http_status == 200 else f"http_{http_status}",
    )
    ctx.write_json(
        "ground_response.json",
        {"http_status": http_status, "elapsed_s": elapsed, "response": resp if isinstance(resp, dict) else {"raw": resp}},
    )

    if http_status != 200 or not isinstance(resp, dict):
        # Check unavailable wording
        blob = json.dumps(resp).lower() if resp is not None else ""
        if "unavailable" in blob or "not loaded" in blob or "warming" in blob:
            ctx.verdict = "PERCEPTION_BACKEND_NOT_READY"
        else:
            ctx.verdict = "GROUND_CAPABILITY_FAIL"
        return _finish(ctx, vlm_pass=True, keywords=keywords, parsed_vlm=parsed, validation=validation)

    detections = resp.get("detections")
    gdino_id = resp.get("gdino_model_id")
    sam2_id = resp.get("sam2_checkpoint") or resp.get("sam2_model_id")
    latency = resp.get("latency_ms")
    ground_errors: list[str] = []
    if not isinstance(detections, list):
        ground_errors.append("detections_not_list")
    if is_fake_model_id(gdino_id):
        ground_errors.append(f"gdino_model_id_invalid:{gdino_id!r}")
    if is_fake_model_id(sam2_id):
        ground_errors.append(f"sam2_checkpoint_invalid:{sam2_id!r}")
    try:
        if latency is not None and not (float(latency) < float("inf")):
            ground_errors.append("latency_not_finite")
    except (TypeError, ValueError):
        ground_errors.append("latency_invalid")

    keyword_detection_map: dict[str, list[dict[str, Any]]] = {k: [] for k in keywords}
    if isinstance(detections, list):
        for d in detections:
            if not isinstance(d, dict):
                continue
            label = str(d.get("label", "")).strip()
            for k in keywords:
                if k.lower() == label.lower() or k.lower() in label.lower() or label.lower() in k.lower():
                    keyword_detection_map[k].append(
                        {"label": label, "score": d.get("score"), "box_xyxy": d.get("box_xyxy")}
                    )

    ctx.write_json(
        "ground_validation.json",
        {
            "errors": ground_errors,
            "gdino_model_id": gdino_id,
            "sam2_checkpoint": sam2_id,
            "detection_count": len(detections) if isinstance(detections, list) else None,
            "keyword_detection_map": keyword_detection_map,
        },
    )
    if ground_errors:
        ctx.verdict = "GROUND_CAPABILITY_FAIL"
        return _finish(
            ctx,
            vlm_pass=True,
            keywords=keywords,
            parsed_vlm=parsed,
            validation=validation,
            ground=resp,
            keyword_detection_map=keyword_detection_map,
        )

    assert isinstance(detections, list)
    if len(detections) == 0:
        ctx.verdict = "GROUND_VALID_EMPTY"
        return _finish(
            ctx,
            vlm_pass=True,
            keywords=keywords,
            parsed_vlm=parsed,
            validation=validation,
            ground=resp,
            keyword_detection_map=keyword_detection_map,
        )

    selection = select_detection(detections, keywords)
    if selection is None:
        ctx.verdict = "GROUND_CAPABILITY_FAIL"
        ctx.write_json("track_selection.json", {"error": "no_valid_box_xyxy"})
        return _finish(
            ctx,
            vlm_pass=True,
            keywords=keywords,
            parsed_vlm=parsed,
            validation=validation,
            ground=resp,
            keyword_detection_map=keyword_detection_map,
        )
    ctx.write_json("track_selection.json", selection)
    chosen = selection["detection"]

    # ---- POST 3: track init ----
    track_init_id = str(uuid.uuid4())
    idx3 = ctx.ledger.plan(
        endpoint_alias="track_init",
        request_id=track_init_id,
        frame_id=vlm_frame_id,
        image_sha256=ctx.vlm_sha,
    )
    track_init_body = {
        "action": "init",
        "frame_index": 0,
        "image_b64": image_b64,
        "init": {
            "target_label": str(chosen.get("label") or "object"),
            "text_prompt": text_prompt,
            "box_threshold": ctx.box_threshold,
            "box_xyxy": [float(x) for x in chosen["box_xyxy"]],
        },
        "meta": {
            "local_request_id": track_init_id,
            "parent_vlm_request_id": vlm_request_id,
            "parent_ground_request_id": ground_request_id,
            "frame_id": vlm_frame_id,
            "image_sha256": ctx.vlm_sha,
            "probe": "v0b2b",
        },
    }
    ctx.write_json(
        "track_init_request_summary.json",
        {
            "request_index": idx3,
            "endpoint_alias": "track_init",
            "url_path": "/track",
            "action": "init",
            "request_id": track_init_id,
            "frame_index": 0,
            "init": track_init_body["init"],
            "meta": track_init_body["meta"],
            "image_b64": "<redacted>",
        },
    )
    http_status, resp, elapsed, err_kind = ctx.http_post(
        f"{ctx.perception_base.rstrip('/')}/track", track_init_body, TRACK_TIMEOUT_S
    )
    ctx.posts_executed.append("track_init")
    track_init_resp = resp
    if err_kind == "timeout":
        ctx.ledger.finalize(request_index=idx3, status="timeout", http_status=http_status, elapsed_s=elapsed, error="timeout")
        ctx.write_json("track_init_response.json", {"error": "timeout", "elapsed_s": elapsed})
        ctx.verdict = "TRACK_INIT_FAIL"
        return _finish(
            ctx,
            vlm_pass=True,
            keywords=keywords,
            parsed_vlm=parsed,
            validation=validation,
            keyword_detection_map=keyword_detection_map,
            selection=selection,
            gdino_id=gdino_id,
            sam2_id=sam2_id,
        )

    ctx.ledger.finalize(
        request_index=idx3,
        status="completed" if http_status == 200 else "failed",
        http_status=http_status,
        elapsed_s=elapsed,
        error=None if http_status == 200 else f"http_{http_status}",
    )
    ctx.write_json(
        "track_init_response.json",
        {
            "http_status": http_status,
            "elapsed_s": elapsed,
            "response": track_init_resp if isinstance(track_init_resp, dict) else {"raw": track_init_resp},
        },
    )

    session_id = None
    track_id = None
    init_ok = False
    if http_status == 200 and isinstance(track_init_resp, dict):
        session_id = track_init_resp.get("session_id")
        tracks = track_init_resp.get("tracks")
        if session_id and isinstance(tracks, list) and tracks:
            first = tracks[0] if isinstance(tracks[0], dict) else {}
            track_id = first.get("track_id")
            box_ok = isinstance(first.get("box_xyxy"), (list, tuple)) and len(first.get("box_xyxy") or []) == 4
            # track_id may be integer 0 — do not use truthiness
            init_ok = track_id is not None and str(track_id) != "" and box_ok
    if not init_ok:
        ctx.verdict = "TRACK_INIT_FAIL"
        return _finish(
            ctx,
            vlm_pass=True,
            keywords=keywords,
            parsed_vlm=parsed,
            validation=validation,
            keyword_detection_map=keyword_detection_map,
            selection=selection,
            session_id=session_id,
            track_id=track_id,
            gdino_id=gdino_id,
            sam2_id=sam2_id,
        )

    # ---- POST 4: track step ----
    track_step_id = str(uuid.uuid4())
    track_frame_id = str(uuid.uuid4())
    idx4 = ctx.ledger.plan(
        endpoint_alias="track_step",
        request_id=track_step_id,
        frame_id=track_frame_id,
        image_sha256=ctx.track_sha,
    )
    track_image_b64 = load_image_b64(ctx.track_image)
    track_step_body = {
        "action": "step",
        "frame_index": 10,
        "image_b64": track_image_b64,
        "session_id": session_id,
        "meta": {
            "local_request_id": track_step_id,
            "parent_track_init_request_id": track_init_id,
            "frame_id": track_frame_id,
            "image_sha256": ctx.track_sha,
            "expected_track_id": track_id,
            "probe": "v0b2b",
        },
    }
    ctx.write_json(
        "track_step_request_summary.json",
        {
            "request_index": idx4,
            "endpoint_alias": "track_step",
            "url_path": "/track",
            "action": "step",
            "request_id": track_step_id,
            "session_id": session_id,
            "frame_index": 10,
            "image_sha256": ctx.track_sha,
            "image_b64": "<redacted>",
        },
    )
    http_status, step_resp, elapsed, err_kind = ctx.http_post(
        f"{ctx.perception_base.rstrip('/')}/track", track_step_body, TRACK_TIMEOUT_S
    )
    ctx.posts_executed.append("track_step")
    if err_kind == "timeout":
        ctx.ledger.finalize(request_index=idx4, status="timeout", http_status=http_status, elapsed_s=elapsed, error="timeout")
        ctx.write_json("track_step_response.json", {"error": "timeout", "elapsed_s": elapsed})
        ctx.verdict = "TRACK_STEP_FAIL"
        return _finish(
            ctx, vlm_pass=True, keywords=keywords, parsed_vlm=parsed, validation=validation,
            keyword_detection_map=keyword_detection_map, selection=selection,
            session_id=session_id, track_id=track_id,
        )

    ctx.ledger.finalize(
        request_index=idx4,
        status="completed" if http_status == 200 else "failed",
        http_status=http_status,
        elapsed_s=elapsed,
        error=None if http_status == 200 else f"http_{http_status}",
    )
    ctx.write_json(
        "track_step_response.json",
        {"http_status": http_status, "elapsed_s": elapsed, "response": step_resp if isinstance(step_resp, dict) else {"raw": step_resp}},
    )

    step_ok = False
    track_state_native = False
    step_obs: dict[str, Any] = {}
    if http_status == 200 and isinstance(step_resp, dict):
        sid2 = step_resp.get("session_id")
        tracks = step_resp.get("tracks") or []
        associated = None
        if isinstance(tracks, list):
            for t in tracks:
                if isinstance(t, dict) and str(t.get("track_id")) == str(track_id):
                    associated = t
                    break
            if associated is None and tracks and isinstance(tracks[0], dict):
                associated = tracks[0]
                step_obs["track_id_association"] = "first_track_fallback_local"
            else:
                step_obs["track_id_association"] = "exact" if associated else "missing"
        track_state_native = "track_state" in step_resp or (
            isinstance(associated, dict) and "track_state" in associated
        )
        step_ok = (
            sid2 == session_id
            and associated is not None
            and isinstance(associated.get("box_xyxy"), (list, tuple))
        )
        if associated:
            step_obs.update(
                {
                    "re_detected": step_resp.get("re_detected"),
                    "box_xyxy": associated.get("box_xyxy"),
                    "mask_area": associated.get("mask_area"),
                    "score": associated.get("sam2_score", associated.get("score")),
                    "velocity_xy_px_s": associated.get("velocity_xy_px_s"),
                    "speed_px_s": associated.get("speed_px_s"),
                    "track_id": associated.get("track_id"),
                    "observed_status_note": (
                        "legacy response has no native track_state; "
                        "do not claim lost/reacquired from server"
                    ),
                }
            )
    ctx.write_json(
        "track_step_validation.json",
        {
            "pass": step_ok,
            "session_id_match": isinstance(step_resp, dict) and step_resp.get("session_id") == session_id,
            "track_state_native": track_state_native,
            "observations": step_obs,
        },
    )
    if not step_ok:
        ctx.verdict = "TRACK_STEP_FAIL"
        return _finish(
            ctx, vlm_pass=True, keywords=keywords, parsed_vlm=parsed, validation=validation,
            keyword_detection_map=keyword_detection_map, selection=selection,
            session_id=session_id, track_id=track_id, track_state_native=track_state_native,
        )

    # All gates passed under legacy constraints
    ctx.verdict = "LEGACY_GATEWAY_FEASIBLE"
    return _finish(
        ctx,
        vlm_pass=True,
        keywords=keywords,
        parsed_vlm=parsed,
        validation=validation,
        keyword_detection_map=keyword_detection_map,
        selection=selection,
        session_id=session_id,
        track_id=track_id,
        track_state_native=track_state_native,
        step_obs=step_obs,
        gdino_id=gdino_id,
        sam2_id=sam2_id,
    )


def _finish(
    ctx: ProbeContext,
    *,
    vlm_pass: bool,
    keywords: list[str] | None = None,
    parsed_vlm: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    ground: dict[str, Any] | None = None,
    keyword_detection_map: dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
    session_id: str | None = None,
    track_id: str | None = None,
    track_state_native: bool | None = None,
    step_obs: dict[str, Any] | None = None,
    gdino_id: Any = None,
    sam2_id: Any = None,
) -> int:
    post_count = len(ctx.posts_executed)
    if ctx.ledger is not None:
        post_count = ctx.ledger.post_count
    ctx.summary = {
        "verdict": ctx.verdict,
        "post_count": post_count,
        "posts_executed": list(ctx.posts_executed),
        "vlm_schema_pass": vlm_pass,
        "keywords": keywords or [],
        "keyword_detection_map": keyword_detection_map,
        "gdino_model_id": gdino_id,
        "sam2_checkpoint": sam2_id,
        "selection": redact_for_log(selection) if selection else None,
        "session_id": session_id,
        "track_id": track_id,
        "track_state_native": track_state_native,
        "step_observations": step_obs,
        "ids_echoed_by_remote": False,  # never claim ID continuity from remote echo
        "id_continuity": "local_gateway_only",
        "five_stage_paper_validated": False,
        "negative_sample_scene": True,
        "retries": 0,
        "credentials_read": False,
        "tunnel_modified": False,
        "remote_modified": False,
        "parsed_vlm_keys": sorted(parsed_vlm.keys()) if parsed_vlm else [],
        "vlm_validation_errors": (validation or {}).get("errors"),
        "gateway_worth_implementing": ctx.verdict == "LEGACY_GATEWAY_FEASIBLE",
        "completed_at": utc_now(),
    }
    ctx.write_json("probe_summary.json", ctx.summary)
    return 0 if ctx.verdict in {"LEGACY_GATEWAY_FEASIBLE", "GROUND_VALID_EMPTY", "DRY_RUN"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V0-B2B legacy endpoint probe (max 4 POSTs)")
    p.add_argument("--execute", action="store_true", help="Actually POST (default: dry-run)")
    p.add_argument("--vlm-image", type=Path, required=True)
    p.add_argument("--track-image", type=Path, required=True)
    p.add_argument("--artifact-manifest", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--box-threshold", type=float, default=0.2, help="From perception_client.yaml")
    p.add_argument("--text-threshold", type=float, default=0.25, help="OpenAPI/server default")
    p.add_argument("--max-detections", type=int, default=10, help="OpenAPI/server default")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    vlm_base = os.environ.get("GMROBOT_VLM_BASE_URL", "").strip()
    perc_base = os.environ.get("GMROBOT_PERCEPTION_BASE_URL", "").strip()
    if args.execute and (not vlm_base or not perc_base):
        print("ERROR: GMROBOT_VLM_BASE_URL and GMROBOT_PERCEPTION_BASE_URL required for --execute", file=sys.stderr)
        return 2
    # dry-run may omit env

    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        # Allow only if completely empty; ledger check is primary
        if (out / "request_ledger.jsonl").exists():
            print(f"ERROR: ledger exists: {out / 'request_ledger.jsonl'}", file=sys.stderr)
            return 2

    sha_map = load_artifact_sha_map(args.artifact_manifest)
    vlm_name = args.vlm_image.name
    track_name = args.track_image.name
    if vlm_name not in sha_map or track_name not in sha_map:
        print("ERROR: frames not found in artifact manifest", file=sys.stderr)
        return 2
    verify_frame_sha(args.vlm_image, sha_map[vlm_name])
    verify_frame_sha(args.track_image, sha_map[track_name])

    ctx = ProbeContext(
        output_dir=out,
        execute=bool(args.execute),
        vlm_base=vlm_base or "http://127.0.0.1:18080",
        perception_base=perc_base or "http://127.0.0.1:18082",
        vlm_image=args.vlm_image,
        track_image=args.track_image,
        vlm_sha=sha_map[vlm_name],
        track_sha=sha_map[track_name],
        box_threshold=float(args.box_threshold),
        text_threshold=float(args.text_threshold),
        max_detections=int(args.max_detections),
    )
    try:
        return run_probe(ctx)
    except ProbeError as exc:
        err = {"error": str(exc), "verdict": "PROBE_PRECHECK_FAIL", "at": utc_now()}
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / "probe_summary.json").write_text(json.dumps(err, indent=2) + "\n")
        except OSError:
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
