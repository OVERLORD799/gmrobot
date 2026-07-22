#!/usr/bin/env python3
"""Legacy perception v0.1 → V0-A canonical schema gateway + track session."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .schema import SCHEMA_VERSION, keywords_to_text_prompt, normalize_keywords

REMOTE_CONTRACT = "legacy_v0_1"
ID_SOURCE = "local_gateway"
TRACK_STATE_SOURCE = "legacy_gateway_inferred"

HttpPostFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def is_valid_track_id(track_id: Any) -> bool:
    """track_id=0 is valid. Never use bool(track_id)."""
    if track_id is None:
        return False
    if isinstance(track_id, bool):
        return False
    if isinstance(track_id, (int, float)):
        return True
    if isinstance(track_id, str) and track_id.strip() != "":
        return True
    return False


def normalize_track_id(track_id: Any) -> str | None:
    if not is_valid_track_id(track_id):
        return None
    try:
        return str(int(track_id))
    except (TypeError, ValueError):
        return str(track_id)


def stable_detection_id(*, label: str, box_xyxy: list[float], index: int) -> str:
    raw = f"{index}|{label}|{','.join(f'{x:.4f}' for x in box_xyxy)}"
    return "det_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def label_matches_keyword(label: str, keyword: str) -> bool:
    lab = str(label or "").strip().lower()
    kw = str(keyword or "").strip().lower()
    if not lab or not kw:
        # Empty label must NEVER count as keyword match
        return False
    return lab == kw or kw in lab or lab in kw


def build_keyword_detection_map(
    keywords: list[str], detections: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in keywords}
    for d in detections:
        label = str(d.get("label") or "")
        if not label.strip():
            continue
        for k in keywords:
            if label_matches_keyword(label, k):
                out[k].append(
                    {
                        "detection_id": d.get("detection_id"),
                        "label": label,
                        "score": d.get("score"),
                        "box_xyxy": d.get("box_xyxy"),
                    }
                )
    return out


def convert_legacy_ground_response(
    remote: dict[str, Any] | None,
    *,
    request_id: str,
    frame_id: str,
    parent_request_id: str = "",
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Convert legacy GroundResponse to canonical perception payload."""
    kw = normalize_keywords(keywords)
    mapping_errors: list[str] = []

    if not remote:
        return {
            "ok": False,
            "request_id": request_id,
            "frame_id": frame_id,
            "parent_request_id": parent_request_id,
            "detections": [],
            "keyword_detection_map": {k: [] for k in kw},
            "model_versions": {},
            "latency_ms": 0.0,
            "schema_version": SCHEMA_VERSION,
            "remote_contract": REMOTE_CONTRACT,
            "id_source": ID_SOURCE,
            "mapping_source": ID_SOURCE,
            "gateway_parse_ok": False,
            "gateway_mapping_errors": ["empty_response"],
            "error": "empty legacy ground response",
        }

    if remote.get("ok") is False or remote.get("error"):
        return {
            "ok": False,
            "request_id": request_id,
            "frame_id": frame_id,
            "parent_request_id": parent_request_id,
            "detections": [],
            "keyword_detection_map": {k: [] for k in kw},
            "model_versions": {},
            "latency_ms": float(remote.get("latency_ms") or 0.0),
            "schema_version": SCHEMA_VERSION,
            "remote_contract": REMOTE_CONTRACT,
            "id_source": ID_SOURCE,
            "mapping_source": ID_SOURCE,
            "gateway_parse_ok": False,
            "gateway_mapping_errors": ["remote_error"],
            "error": str(remote.get("error") or "ground failed"),
        }

    raw_dets = remote.get("detections")
    if not isinstance(raw_dets, list):
        mapping_errors.append("detections_not_list")
        raw_dets = []

    detections: list[dict[str, Any]] = []
    for i, d in enumerate(raw_dets):
        if not isinstance(d, dict):
            mapping_errors.append(f"detection_{i}_not_dict")
            continue
        box = d.get("box_xyxy")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            mapping_errors.append(f"detection_{i}_bad_box")
            continue
        try:
            box_f = [float(x) for x in box]
        except (TypeError, ValueError):
            mapping_errors.append(f"detection_{i}_non_numeric_box")
            continue
        label = str(d.get("label") or "")
        try:
            score = float(d.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        mask_area = d.get("mask_area")
        try:
            mask_area_f = float(mask_area) if mask_area is not None else 0.0
        except (TypeError, ValueError):
            mask_area_f = 0.0
        sam2_score = d.get("sam2_score")
        try:
            sam2_f = float(sam2_score) if sam2_score is not None else None
        except (TypeError, ValueError):
            sam2_f = None
        # Ground detections do not yet have a track — leave track_id unset (None)
        # and track_state empty until track adapter assigns.
        det = {
            "detection_id": stable_detection_id(label=label, box_xyxy=box_f, index=i),
            "label": label,
            "score": score,
            "box_xyxy": box_f,
            "mask_available": mask_area_f > 0 or sam2_f is not None,
            "mask_area": mask_area_f,
            "sam2_score": sam2_f,
            "track_id": None,
            "track_id_str": None,
            "track_state": "",
            "track_state_native": False,
            "track_state_source": TRACK_STATE_SOURCE,
        }
        detections.append(det)

    gdino = str(remote.get("gdino_model_id") or "")
    sam2 = str(remote.get("sam2_checkpoint") or remote.get("sam2_model_id") or "")
    try:
        latency = float(remote.get("latency_ms") or 0.0)
    except (TypeError, ValueError):
        latency = 0.0

    kmap = build_keyword_detection_map(kw, detections)
    return {
        "ok": True,
        "request_id": request_id,
        "frame_id": frame_id,
        "parent_request_id": parent_request_id,
        "detections": detections,
        "keyword_detection_map": kmap,
        "model_versions": {
            "gdino_model_id": gdino,
            "sam2_model_id": sam2,
            "sam2_checkpoint": sam2,
        },
        "latency_ms": latency,
        "schema_version": SCHEMA_VERSION,
        "remote_contract": REMOTE_CONTRACT,
        "id_source": ID_SOURCE,
        "mapping_source": ID_SOURCE,
        "gateway_parse_ok": len(mapping_errors) == 0,
        "gateway_mapping_errors": mapping_errors,
    }


def select_detection_for_track(
    detections: list[dict[str, Any]], keywords: list[str] | None = None
) -> dict[str, Any] | None:
    """Prefer keyword-matching non-empty label, then highest score; require box."""
    kw = normalize_keywords(keywords)
    valid: list[dict[str, Any]] = []
    for d in detections:
        box = d.get("box_xyxy")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        valid.append(d)
    if not valid:
        return None

    def score_of(d: dict[str, Any]) -> float:
        try:
            return float(d.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    matched = [
        d
        for d in valid
        if str(d.get("label") or "").strip()
        and any(label_matches_keyword(str(d.get("label")), k) for k in kw)
    ]
    pool = matched if matched else [d for d in valid if str(d.get("label") or "").strip()] or valid
    return sorted(pool, key=score_of, reverse=True)[0]


@dataclass
class LegacyTrackSessionState:
    session_id: str | None = None
    frame_index: int = 0
    last_track_id: str | None = None
    last_track_state: str = "terminated"
    was_lost: bool = False
    # Same-frame retry guard
    failed_this_frame: bool = False
    last_fail_frame_id: str | None = None
    # Local safe alias (never log raw remote session id)
    session_generation: int = 0
    session_ref: str = ""

    def clear(self) -> None:
        self.session_id = None
        self.frame_index = 0
        self.last_track_id = None
        self.last_track_state = "terminated"
        self.was_lost = False
        self.failed_this_frame = False
        self.last_fail_frame_id = None
        # Keep generation so the next successful init gets a new ref.
        self.session_ref = ""

    def bump_alias(self) -> None:
        self.session_generation += 1
        self.session_ref = f"session_{self.session_generation}"


@dataclass
class LegacyPerceptionGateway:
    """Stateful legacy ground/track adapter for FiveStageShadowWorker."""

    http_post: HttpPostFn | None = None
    box_threshold: float = 0.2
    text_threshold: float = 0.25
    max_detections: int = 10
    run_sam2: bool = True
    # If True, after lost/error, next frame with detections may re-init.
    reinit_after_lost: bool = True
    _session: LegacyTrackSessionState = field(default_factory=LegacyTrackSessionState)

    def reset(self) -> dict[str, Any]:
        self._session.clear()
        self._session.last_track_state = "terminated"
        return {
            "ok": True,
            "tracks": [],
            "track_state": "terminated",
            "track_state_native": False,
            "track_state_source": TRACK_STATE_SOURCE,
            "remote_contract": REMOTE_CONTRACT,
            "id_source": ID_SOURCE,
            "session_cleared": True,
        }

    def ground(
        self,
        rgb_or_b64: Any = None,
        *,
        image_b64: str | None = None,
        keywords: list[str] | None = None,
        request_id: str | None = None,
        frame_id: str | None = None,
        parent_request_id: str | None = None,
        run_sam2: bool | None = None,
        meta: dict[str, Any] | None = None,
        allow_default_prompt: bool = False,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        del rgb_or_b64  # gateway tests pass image_b64; live client wraps encoding
        rid = str(request_id or uuid.uuid4())
        fid = str(frame_id or uuid.uuid4())
        parent = str(parent_request_id or (meta or {}).get("parent_request_id") or rid)
        kw = normalize_keywords(keywords)
        if not kw and not allow_default_prompt:
            return {
                "ok": True,
                "request_id": rid,
                "frame_id": fid,
                "parent_request_id": parent,
                "detections": [],
                "keyword_detection_map": {},
                "perception_status": "skipped_no_keywords",
                "latency_ms": 0.0,
                "schema_version": SCHEMA_VERSION,
                "remote_contract": REMOTE_CONTRACT,
                "id_source": ID_SOURCE,
                "mapping_source": ID_SOURCE,
                "gateway_parse_ok": True,
                "gateway_mapping_errors": [],
            }
        if image_b64 is None:
            return {
                "ok": False,
                "request_id": rid,
                "frame_id": fid,
                "parent_request_id": parent,
                "error": "image_b64 required for legacy ground gateway unit path",
                "detections": [],
                "keyword_detection_map": {k: [] for k in kw},
                "gateway_parse_ok": False,
                "gateway_mapping_errors": ["missing_image_b64"],
                "remote_contract": REMOTE_CONTRACT,
                "id_source": ID_SOURCE,
            }
        text_prompt = keywords_to_text_prompt(kw)
        payload = {
            "text_prompt": text_prompt,
            "image_b64": image_b64,
            "box_threshold": self.box_threshold,
            "text_threshold": self.text_threshold,
            "max_detections": self.max_detections,
            "run_sam2": self.run_sam2 if run_sam2 is None else bool(run_sam2),
            "meta": {
                **(meta or {}),
                "local_request_id": rid,
                "frame_id": fid,
                "parent_request_id": parent,
                "keywords": kw,
            },
        }
        if self.http_post is None:
            return {
                "ok": False,
                "request_id": rid,
                "frame_id": fid,
                "parent_request_id": parent,
                "error": "no http_post transport",
                "detections": [],
                "keyword_detection_map": {k: [] for k in kw},
                "gateway_parse_ok": False,
                "gateway_mapping_errors": ["no_transport"],
                "remote_contract": REMOTE_CONTRACT,
                "id_source": ID_SOURCE,
            }
        remote = self.http_post("/ground", payload)
        return convert_legacy_ground_response(
            remote,
            request_id=rid,
            frame_id=fid,
            parent_request_id=parent,
            keywords=kw,
        )

    def track(
        self,
        rgb_or_b64: Any = None,
        *,
        image_b64: str | None = None,
        parent_request_id: str | None = None,
        frame_id: str | None = None,
        detections: list[dict[str, Any]] | None = None,
        keywords: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Worker-facing track callback with explicit session lifecycle."""
        del rgb_or_b64
        fid = str(frame_id or uuid.uuid4())
        parent = str(parent_request_id or "")
        dets = list(detections or [])
        sess = self._session

        # New frame clears same-frame retry latch (never re-POST on the failed frame).
        if sess.last_fail_frame_id and sess.last_fail_frame_id != fid:
            sess.failed_this_frame = False

        # Same-frame failure: do not auto re-init
        if sess.failed_this_frame and sess.last_fail_frame_id == fid:
            return self._canonical_track_error(
                frame_id=fid,
                parent_request_id=parent,
                error="session_failed_same_frame_no_retry",
                track_state="lost",
            )

        if image_b64 is None:
            return self._canonical_track_error(
                frame_id=fid,
                parent_request_id=parent,
                error="image_b64 required",
                track_state="lost",
            )

        if self.http_post is None:
            return self._canonical_track_error(
                frame_id=fid,
                parent_request_id=parent,
                error="no http_post transport",
                track_state="lost",
            )

        # No session yet → init from detections
        if sess.session_id is None:
            if not dets:
                return {
                    "ok": True,
                    "request_id": parent,
                    "frame_id": fid,
                    "parent_request_id": parent,
                    "tracks": [],
                    "track_session_id": "",
                    "track_state": "terminated",
                    "track_state_native": False,
                    "track_state_source": TRACK_STATE_SOURCE,
                    "remote_contract": REMOTE_CONTRACT,
                    "id_source": ID_SOURCE,
                    "gateway_parse_ok": True,
                    "gateway_mapping_errors": [],
                    "perception_status": "skipped_no_detections",
                }
            chosen = select_detection_for_track(dets, keywords)
            if chosen is None:
                return self._canonical_track_error(
                    frame_id=fid,
                    parent_request_id=parent,
                    error="no_valid_detection_for_init",
                    track_state="lost",
                )
            return self._do_init(
                image_b64=image_b64,
                chosen=chosen,
                frame_id=fid,
                parent_request_id=parent,
                meta=meta,
            )

        # Existing session → step
        return self._do_step(
            image_b64=image_b64,
            frame_id=fid,
            parent_request_id=parent,
            meta=meta,
        )

    def _do_init(
        self,
        *,
        image_b64: str,
        chosen: dict[str, Any],
        frame_id: str,
        parent_request_id: str,
        meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = {
            "action": "init",
            "frame_index": 0,
            "image_b64": image_b64,
            "init": {
                "target_label": str(chosen.get("label") or "object"),
                "box_xyxy": [float(x) for x in chosen["box_xyxy"]],
                "box_threshold": self.box_threshold,
            },
            "meta": {**(meta or {}), "parent_request_id": parent_request_id, "frame_id": frame_id},
        }
        assert self.http_post is not None
        remote = self.http_post("/track", payload)
        return self._ingest_track_remote(
            remote,
            frame_id=frame_id,
            parent_request_id=parent_request_id,
            action="init",
        )

    def _do_step(
        self,
        *,
        image_b64: str,
        frame_id: str,
        parent_request_id: str,
        meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        sess = self._session
        expected_session_id = sess.session_id
        next_index = int(sess.frame_index) + 1
        payload = {
            "action": "step",
            "session_id": expected_session_id,
            "frame_index": next_index,
            "image_b64": image_b64,
            "meta": {**(meta or {}), "parent_request_id": parent_request_id, "frame_id": frame_id},
        }
        assert self.http_post is not None
        remote = self.http_post("/track", payload)
        return self._ingest_track_remote(
            remote,
            frame_id=frame_id,
            parent_request_id=parent_request_id,
            action="step",
            expected_frame_index=next_index,
            expected_session_id=expected_session_id,
        )

    def _ingest_track_remote(
        self,
        remote: dict[str, Any] | None,
        *,
        frame_id: str,
        parent_request_id: str,
        action: str,
        expected_frame_index: int | None = None,
        expected_session_id: str | None = None,
    ) -> dict[str, Any]:
        sess = self._session
        if not remote or remote.get("ok") is False or remote.get("error"):
            return self._mark_fail(
                frame_id=frame_id,
                parent_request_id=parent_request_id,
                error=str((remote or {}).get("error") or "track_http_or_empty"),
                action=action,
            )

        response_session_id = remote.get("session_id")
        if not isinstance(response_session_id, str) or not response_session_id.strip():
            return self._mark_fail(
                frame_id=frame_id,
                parent_request_id=parent_request_id,
                error="missing_session_id",
                action=action,
            )

        # Continuity compare BEFORE any session commit / redaction (step only).
        session_match: bool | None
        session_match_applicable: bool
        session_continuity_verified: bool
        if action == "step":
            session_match_applicable = True
            session_match = bool(
                expected_session_id is not None
                and response_session_id == expected_session_id
            )
            session_continuity_verified = bool(session_match)
            if not session_match:
                return self._session_mismatch_result(
                    frame_id=frame_id,
                    parent_request_id=parent_request_id,
                )
        else:
            session_match = None
            session_match_applicable = False
            session_continuity_verified = False

        tracks_raw = remote.get("tracks") or []
        if not isinstance(tracks_raw, list):
            tracks_raw = []

        # Infer state
        if action == "init":
            if not tracks_raw:
                return self._mark_fail(
                    frame_id=frame_id,
                    parent_request_id=parent_request_id,
                    error="init_no_tracks",
                    action=action,
                )
            state = "reacquired" if sess.was_lost else "initialized"
        else:
            # step
            if not tracks_raw:
                state = "lost"
            else:
                state = "tracking"

        canon_tracks: list[dict[str, Any]] = []
        primary_tid: str | None = None
        for t in tracks_raw:
            if not isinstance(t, dict):
                continue
            tid_raw = t.get("track_id")
            tid = normalize_track_id(tid_raw)
            if tid is None:
                continue
            if primary_tid is None:
                primary_tid = tid
            box = t.get("box_xyxy")
            box_f = None
            if isinstance(box, (list, tuple)) and len(box) == 4:
                try:
                    box_f = [float(x) for x in box]
                except (TypeError, ValueError):
                    box_f = None
            canon_tracks.append(
                {
                    "track_id": tid_raw if isinstance(tid_raw, int) else tid,
                    "track_id_str": tid,
                    "label": str(t.get("label") or ""),
                    "box_xyxy": box_f,
                    "mask_area": t.get("mask_area"),
                    "sam2_score": t.get("sam2_score", t.get("score")),
                    "velocity_xy_px_s": t.get("velocity_xy_px_s"),
                    "speed_px_s": t.get("speed_px_s"),
                    "direction_deg": t.get("direction_deg"),
                    "center_xy": t.get("center_xy"),
                    "track_state": state,
                    "track_state_native": False,
                    "track_state_source": TRACK_STATE_SOURCE,
                }
            )

        if action == "step" and state == "lost":
            sess.was_lost = True
            sess.last_track_state = "lost"
            # Clear session so next frame may re-init if policy allows
            if self.reinit_after_lost:
                sess.session_id = None
                sess.frame_index = 0
                sess.session_ref = ""
            return {
                "ok": True,
                "request_id": parent_request_id,
                "frame_id": frame_id,
                "parent_request_id": parent_request_id,
                "tracks": [],
                "track_session_id": "<redacted>",
                "session_present": True,
                "session_match": session_match,
                "session_match_applicable": session_match_applicable,
                "session_continuity_verified": session_continuity_verified,
                "session_generation": sess.session_generation,
                "session_ref": sess.session_ref or f"session_{sess.session_generation}",
                "track_id": sess.last_track_id or "",
                "track_state": "lost",
                "track_state_native": False,
                "track_state_source": TRACK_STATE_SOURCE,
                "re_detected": remote.get("re_detected"),
                "latency_ms": remote.get("latency_ms"),
                "remote_contract": REMOTE_CONTRACT,
                "id_source": ID_SOURCE,
                "gateway_parse_ok": True,
                "gateway_mapping_errors": [],
                "frame_index": remote.get("frame_index", expected_frame_index),
            }

        if not canon_tracks:
            return self._mark_fail(
                frame_id=frame_id,
                parent_request_id=parent_request_id,
                error="no_valid_tracks",
                action=action,
            )

        # Commit session (response id already verified for step)
        if action == "init":
            sess.bump_alias()
        sess.session_id = response_session_id
        sess.frame_index = int(remote.get("frame_index", expected_frame_index or 0) or 0)
        sess.last_track_id = primary_tid
        sess.last_track_state = state
        if state in ("initialized", "tracking", "reacquired"):
            sess.was_lost = False
        sess.failed_this_frame = False
        sess.last_fail_frame_id = None

        return {
            "ok": True,
            "request_id": parent_request_id,
            "frame_id": frame_id,
            "parent_request_id": parent_request_id,
            "tracks": canon_tracks,
            "track_session_id": "<redacted>",
            "session_present": True,
            "session_match": session_match,
            "session_match_applicable": session_match_applicable,
            "session_continuity_verified": session_continuity_verified,
            "session_generation": sess.session_generation,
            "session_ref": sess.session_ref,
            "track_id": canon_tracks[0].get("track_id"),
            "track_id_str": canon_tracks[0].get("track_id_str"),
            "track_state": state,
            "track_state_native": False,
            "track_state_source": TRACK_STATE_SOURCE,
            "re_detected": remote.get("re_detected"),
            "latency_ms": remote.get("latency_ms"),
            "remote_contract": REMOTE_CONTRACT,
            "id_source": ID_SOURCE,
            "gateway_parse_ok": True,
            "gateway_mapping_errors": [],
            "frame_index": sess.frame_index,
        }

    def _session_mismatch_result(
        self,
        *,
        frame_id: str,
        parent_request_id: str,
    ) -> dict[str, Any]:
        """Step continuity failure: keep local session; never commit foreign id."""
        sess = self._session
        sess.failed_this_frame = True
        sess.last_fail_frame_id = frame_id
        # Do NOT clear or overwrite sess.session_id / generation / ref.
        return {
            "ok": False,
            "request_id": parent_request_id,
            "frame_id": frame_id,
            "parent_request_id": parent_request_id,
            "tracks": [],
            "track_session_id": "<redacted>" if sess.session_id else "",
            "session_present": bool(sess.session_id),
            "session_match": False,
            "session_match_applicable": True,
            "session_continuity_verified": False,
            "session_generation": sess.session_generation,
            "session_ref": sess.session_ref,
            "track_id": sess.last_track_id if sess.last_track_id is not None else "",
            "track_state": sess.last_track_state or "lost",
            "track_state_native": False,
            "track_state_source": TRACK_STATE_SOURCE,
            "error": "session_id_mismatch",
            "error_type": "session_id_mismatch",
            "remote_contract": REMOTE_CONTRACT,
            "id_source": ID_SOURCE,
            "gateway_parse_ok": False,
            "gateway_mapping_errors": ["session_id_mismatch"],
        }

    def _mark_fail(
        self,
        *,
        frame_id: str,
        parent_request_id: str,
        error: str,
        action: str = "step",
    ) -> dict[str, Any]:
        self._session.failed_this_frame = True
        self._session.last_fail_frame_id = frame_id
        self._session.was_lost = True
        self._session.last_track_state = "lost"
        # Do not clear session_id here if we want "no same-frame reinit";
        # clear so next *different* frame can re-init when policy allows.
        # Keep session_id only for same-frame guard; clear for next frame reinit.
        self._session.session_id = None
        self._session.session_ref = ""
        return self._canonical_track_error(
            frame_id=frame_id,
            parent_request_id=parent_request_id,
            error=error,
            track_state="lost",
            action=action,
        )

    def _canonical_track_error(
        self,
        *,
        frame_id: str,
        parent_request_id: str,
        error: str,
        track_state: str,
        action: str = "step",
    ) -> dict[str, Any]:
        applicable = action == "step"
        return {
            "ok": False,
            "request_id": parent_request_id,
            "frame_id": frame_id,
            "parent_request_id": parent_request_id,
            "tracks": [],
            "track_session_id": "",
            "session_present": False,
            "session_match": False if applicable else None,
            "session_match_applicable": applicable,
            "session_continuity_verified": False,
            "session_generation": self._session.session_generation,
            "session_ref": self._session.session_ref,
            "track_state": track_state,
            "track_state_native": False,
            "track_state_source": TRACK_STATE_SOURCE,
            "error": error,
            "error_type": error,
            "remote_contract": REMOTE_CONTRACT,
            "id_source": ID_SOURCE,
            "gateway_parse_ok": False,
            "gateway_mapping_errors": [error],
        }
