"""Offline episode audit helpers for B2/B4 verdict (events + recovery chain)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping

from event_csv import EVENT_CSV_FIELDNAMES, read_event_csv, validate_event_csv_rows
from protocol_vhand import is_b2_proactive_trigger_rule

_TRIGGER_EVENT_TYPES = frozenset({"trigger", "shadow_trigger"})
_TRIGGER_REQUIRED_FIELDS = (
    "ttc_at_trigger",
    "time_to_risk_steps",
    "sweep_attempt_id",
    "sweep_progress",
    "sweep_velocity_x",
    "sweep_velocity_y",
    "sweep_velocity_z",
    "safety_enforcement_mode",
    "shadow_gate_decision",
    "shadow_replan_would_trigger",
)


_EMPTY_ACTIVE_CHAIN_MSG = "no proactive trigger/event chain"
_EMPTY_SHADOW_CHAIN_MSG = "no shadow_trigger rows"


def audit_empty_event_chain(
    rows: list[Mapping[str, str]],
    *,
    enforcement_mode: str,
) -> list[str]:
    """P0-9: header-only or missing proactive/shadow trigger chain."""
    mode = (enforcement_mode or "active").lower()
    if not rows:
        if mode == "shadow":
            return [_EMPTY_SHADOW_CHAIN_MSG]
        return [_EMPTY_ACTIVE_CHAIN_MSG]
    if mode == "shadow":
        if not any((r.get("event_type") or "").strip() == "shadow_trigger" for r in rows):
            return [_EMPTY_SHADOW_CHAIN_MSG]
        return []
    proactive = [
        r for r in rows
        if (r.get("event_type") or "") in _TRIGGER_EVENT_TYPES
        and is_b2_proactive_trigger_rule((r.get("trigger_rule") or "").strip())
    ]
    if not proactive:
        return [_EMPTY_ACTIVE_CHAIN_MSG]
    return []


def audit_events_csv_schema(events_path: str | Path) -> list[str]:
    """Validate header alignment and no None keys/values."""
    p = Path(events_path)
    if not p.is_file() or p.stat().st_size == 0:
        return [f"events CSV missing or empty: {p}"]
    with p.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return ["events CSV has no header"]
        header_cols = [c for c in reader.fieldnames if c]
        if tuple(header_cols) != EVENT_CSV_FIELDNAMES:
            return [
                f"events header mismatch: expected {len(EVENT_CSV_FIELDNAMES)} cols, "
                f"got {len(header_cols)}"
            ]
        rows: list[dict[str, str]] = []
        for i, row in enumerate(reader):
            clean = {k: ("" if v is None else str(v)) for k, v in row.items() if k}
            if None in clean.values():
                return [f"row {i}: contains None value"]
            if None in clean:
                return [f"row {i}: contains None key"]
            rows.append(clean)
    return validate_event_csv_rows(rows)


def audit_trigger_row_fields(rows: list[Mapping[str, str]]) -> list[str]:
    """Trigger/shadow_trigger rows must carry TTC + sweep audit columns."""
    errors: list[str] = []
    for i, row in enumerate(rows):
        et = (row.get("event_type") or "").strip()
        if et not in _TRIGGER_EVENT_TYPES:
            continue
        rule = (row.get("trigger_rule") or "").strip()
        if not is_b2_proactive_trigger_rule(rule):
            continue
        for col in _TRIGGER_REQUIRED_FIELDS:
            if col not in row:
                errors.append(f"row {i} ({et}): missing column {col}")
        ttc = (row.get("ttc_at_trigger") or "").strip()
        ttr = (row.get("time_to_risk_steps") or "").strip()
        if not ttc:
            errors.append(f"row {i} ({et}): empty ttc_at_trigger for rule={rule}")
        if not ttr:
            errors.append(f"row {i} ({et}): empty time_to_risk_steps for rule={rule}")
        try:
            float(ttc)
            int(ttr)
        except ValueError:
            errors.append(f"row {i} ({et}): non-numeric ttc/time_to_risk_steps")
    return errors


def audit_trigger_apply_latency(rows: list[Mapping[str, str]]) -> tuple[list[str], int]:
    """Return (errors, max_latency_steps) for trigger→applied pairs by event_id."""
    errors: list[str] = []
    triggers_by_id: dict[str, list[tuple[int, Mapping[str, str]]]] = {}
    outcomes_by_id: dict[str, tuple[int, str, Mapping[str, str]]] = {}
    unpaired_triggers: list[tuple[int, str]] = []

    for row in rows:
        et = (row.get("event_type") or "").strip()
        eid = (row.get("event_id") or "").strip()
        try:
            step = int(row.get("sim_step", -1))
        except ValueError:
            step = -1
        if et in _TRIGGER_EVENT_TYPES and is_b2_proactive_trigger_rule(
            (row.get("trigger_rule") or "").strip()
        ):
            if eid:
                triggers_by_id.setdefault(eid, []).append((step, row))
            else:
                unpaired_triggers.append((step, (row.get("trigger_rule") or "")))
        elif et in ("applied", "apply_failed", "apply_cancelled") and eid:
            outcomes_by_id[eid] = (step, et, row)

    max_lat = -1
    for eid, (o_step, o_type, _) in outcomes_by_id.items():
        if o_type != "applied":
            continue
        trig_list = triggers_by_id.get(eid, [])
        if not trig_list:
            errors.append(f"applied event_id={eid} has no matching trigger")
            continue
        t_step = min(s for s, _ in trig_list)
        lat = o_step - t_step
        if lat < 0:
            errors.append(f"event_id={eid}: applied before trigger")
        max_lat = max(max_lat, lat)

    for eid, trig_list in triggers_by_id.items():
        if eid not in outcomes_by_id:
            errors.append(f"trigger event_id={eid} has no apply outcome row")
        elif outcomes_by_id[eid][1] == "applied" and not any(
            is_b2_proactive_trigger_rule((r.get("trigger_rule") or "").strip())
            for _, r in trig_list
        ):
            pass

    if unpaired_triggers:
        for t_step, rule in unpaired_triggers:
            matched = any(
                o_step == t_step and o_type == "applied"
                for o_step, o_type, _ in outcomes_by_id.values()
            )
            if not matched:
                errors.append(
                    f"proactive trigger at step {t_step} (rule={rule}) "
                    f"has no same-step applied row"
                )
    return errors, max_lat


def audit_b4_shadow_events(
    events_path: str | Path,
) -> tuple[list[str], dict[str, int]]:
    """Shadow B4: schema + shadow trigger fields; no applied/retreat allowed."""
    rows = read_event_csv(str(events_path))
    errors: list[str] = []
    summary = {
        "shadow_trigger_count": 0,
        "applied_count": 0,
        "retreat_count": 0,
        "max_trigger_apply_latency": -1,
    }

    errors.extend(audit_events_csv_schema(events_path))
    errors.extend(audit_trigger_row_fields(rows))
    errors.extend(audit_empty_event_chain(rows, enforcement_mode="shadow"))

    for i, row in enumerate(rows):
        et = (row.get("event_type") or "").strip()
        if et == "shadow_trigger":
            summary["shadow_trigger_count"] += 1
        elif et == "applied":
            summary["applied_count"] += 1
            errors.append(f"row {i}: shadow run must not emit applied")
        elif et == "retreat":
            summary["retreat_count"] += 1
            errors.append(f"row {i}: shadow run must not emit retreat")
        elif et == "trigger":
            errors.append(f"row {i}: shadow run must emit shadow_trigger not trigger")

    return errors, summary


def audit_events_for_episode(
    events_path: str | Path,
    *,
    enforcement_mode: str,
    attempts_path: str | Path | None = None,
) -> tuple[list[str], dict[str, int]]:
    """Dispatch event audit by enforcement mode (P0-6)."""
    mode = (enforcement_mode or "active").lower()
    if mode == "shadow":
        return audit_b4_shadow_events(events_path)
    return audit_b2_recovery_chain(events_path, attempts_path)


def audit_b2_recovery_chain(
    events_path: str | Path,
    attempts_path: str | Path | None = None,
) -> tuple[list[str], dict[str, int]]:
    """Validate trigger→applied→retreat and attempts redeploy/recovered pairing."""
    rows = read_event_csv(str(events_path))
    errors: list[str] = []
    summary = {
        "proactive_trigger_count": 0,
        "applied_count": 0,
        "retreat_count": 0,
        "redeploy_count": 0,
        "max_trigger_apply_latency": -1,
    }

    schema_errs = audit_events_csv_schema(events_path)
    errors.extend(schema_errs)
    errors.extend(audit_trigger_row_fields(rows))
    errors.extend(audit_empty_event_chain(rows, enforcement_mode="active"))

    lat_errs, max_lat = audit_trigger_apply_latency(rows)
    errors.extend(lat_errs)
    summary["max_trigger_apply_latency"] = max_lat

    proactive = [
        r for r in rows
        if (r.get("event_type") or "") in _TRIGGER_EVENT_TYPES
        and is_b2_proactive_trigger_rule((r.get("trigger_rule") or "").strip())
    ]
    summary["proactive_trigger_count"] = len(proactive)

    applied_rows = [r for r in rows if (r.get("event_type") or "") == "applied"]
    retreat_rows = [r for r in rows if (r.get("event_type") or "") == "retreat"]
    redeploy_rows = [r for r in rows if (r.get("event_type") or "") == "redeploy"]
    summary["applied_count"] = len(applied_rows)
    summary["retreat_count"] = len(retreat_rows)
    summary["redeploy_count"] = len(redeploy_rows)

    for ar in applied_rows:
        eid = (ar.get("event_id") or "").strip()
        try:
            a_step = int(ar.get("sim_step", -1))
        except ValueError:
            a_step = -1
        if eid:
            has_retreat = any(
                (rr.get("event_id") or "").strip() == eid
                for rr in retreat_rows
            )
            if not has_retreat:
                errors.append(f"applied event_id={eid} missing paired retreat")
        else:
            has_retreat = any(
                int(rr.get("sim_step", -2)) == a_step for rr in retreat_rows
            )
            if not has_retreat:
                errors.append(f"applied at step {a_step} missing paired retreat")

    # P0-10: at most one canonical redeploy event per disturbance_attempt_id.
    redeploy_by_attempt: dict[str, int] = {}
    for rr in redeploy_rows:
        aid = str(rr.get("attempt_id") or "").strip() or "?"
        redeploy_by_attempt[aid] = redeploy_by_attempt.get(aid, 0) + 1
    for aid, n in sorted(redeploy_by_attempt.items(), key=lambda x: x[0]):
        if n > 1:
            errors.append(
                f"attempt {aid}: duplicate redeploy events ({n}; canonical allows 1)"
            )

    if attempts_path and Path(attempts_path).is_file():
        with Path(attempts_path).open(newline="") as f:
            for arow in csv.DictReader(f):
                try:
                    retreat_step = int(arow.get("retreat_step", -1) or -1)
                except ValueError:
                    retreat_step = -1
                if retreat_step < 0:
                    continue
                recovered = str(arow.get("recovered", "")).lower() in ("true", "1")
                redeploy = int(arow.get("redeploy_step", -1) or -1)
                terminal = str(arow.get("terminal_success", "")).lower() in ("true", "1")
                aid = str(arow.get("attempt_id", "?")).strip() or "?"
                if not recovered and not terminal and redeploy < 0:
                    errors.append(
                        f"attempt {aid}: retreat without redeploy/recovered/terminal"
                    )
                # Successful recovery attempt: exactly one raw redeploy event.
                if recovered and redeploy >= 0:
                    n_ev = redeploy_by_attempt.get(aid, 0)
                    if n_ev != 1:
                        errors.append(
                            f"attempt {aid}: expected exactly 1 redeploy event, "
                            f"got {n_ev}"
                        )
                # Chain completeness for recovered attempts.
                if recovered:
                    n_trig = sum(
                        1 for r in proactive
                        if str(r.get("attempt_id") or "").strip() == aid
                    )
                    n_app = sum(
                        1 for r in applied_rows
                        if str(r.get("attempt_id") or "").strip() == aid
                    )
                    n_ret = sum(
                        1 for r in retreat_rows
                        if str(r.get("attempt_id") or "").strip() == aid
                    )
                    if n_trig < 1 or n_app < 1 or n_ret < 1:
                        errors.append(
                            f"attempt {aid}: incomplete chain "
                            f"trigger/applied/retreat="
                            f"{n_trig}/{n_app}/{n_ret}"
                        )
    return errors, summary


def audit_b4_shadow_episode(ep: Mapping[str, object]) -> list[str]:
    """B4-Dynamic shadow-only checks from parsed episode metrics."""
    errors: list[str] = []
    mode = str(ep.get("safety_enforcement_mode", "") or "").lower()
    if mode != "shadow":
        errors.append("enforcement mode is not shadow")
    if not bool(ep.get("success", ep.get("task_completed", False))):
        errors.append("task_completed must be True (1/1) for no-control baseline")
    if int(ep.get("d_stop_caused", 0) or 0) > 0:
        errors.append("d_stop_caused must be 0")
    if int(ep.get("d_slow_caused", 0) or 0) > 0:
        errors.append("d_slow_caused must be 0")
    if int(ep.get("d_replan_caused", 0) or 0) > 0:
        errors.append("d_replan_caused must be 0")
    if int(ep.get("shadow_clock_blocked_steps", 0) or 0) != 0:
        errors.append(
            f"shadow_clock_blocked_steps={ep.get('shadow_clock_blocked_steps')} (must be 0)"
        )
    if int(ep.get("shadow_action_modified_steps", 0) or 0) != 0:
        errors.append(
            f"shadow_action_modified_steps={ep.get('shadow_action_modified_steps')} (must be 0)"
        )
    if int(ep.get("shadow_replan_applied_count", 0) or 0) != 0:
        errors.append(
            f"shadow_replan_applied_count={ep.get('shadow_replan_applied_count')} (must be 0)"
        )
    if int(ep.get("shadow_retreat_count", 0) or 0) != 0:
        errors.append(
            f"shadow_retreat_count={ep.get('shadow_retreat_count')} (must be 0)"
        )
    shadow_ttc = int(ep.get("shadow_replan_would_count", 0) or 0)
    if shadow_ttc < 1:
        errors.append("shadow TTC/replan would-trigger count is 0")
    if not str(ep.get("disturbance_trajectory_id", "") or "").strip():
        errors.append("missing disturbance_trajectory_id")
    if int(ep.get("retreat_attempt_count", 0) or 0) > 0:
        errors.append("shadow run must not record proxy retreat attempts")
    return errors
