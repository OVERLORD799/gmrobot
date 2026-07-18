# GMRobot Correctness Review Report

**Date:** 2026-07-01  
**Scope:** Full source tree under `source/GMRobot/GMRobot/safety/` (~6,600 lines Python) + replan subsystem + tests  
**Reviewer:** Automated multi-dimensional review  
**Methodology:** Line-level reading of all 30+ source files, adversarial analysis across 5 dimensions (logic bugs, integration bugs, numerical safety, concurrency/state, test coverage gaps)

---

## Summary

| Severity | Count | Description |
|----------|-------|-------------|
| **P0** (crash/corruption) | 2 | Code paths that can raise unhandled exceptions or produce silently wrong safety decisions |
| **P1** (wrong result) | 8 | Bugs that produce semantically incorrect behavior under specific conditions |
| **P2** (edge case / robustness) | 10 | Issues that don't cause wrong results in normal operation but degrade reliability |

**Overall Assessment:** The codebase is in good shape for a research project approaching paper submission. The safety-critical paths (Tier0 hard stop, TTC computation, envelope distance) are well-guarded. The main concerns are in the replan trigger logic and multi-environment state sharing.

---

## P0 — Crash / Data Corruption

### P0-1: `rule_engine.py:93` — Ambiguous ternary expression risks silent wrong gating

**File:** [source/GMRobot/GMRobot/safety/rule_engine.py:93](source/GMRobot/GMRobot/safety/rule_engine.py#L93)

```python
dist_slow = dist if (use_envelope and dist_ee < warn_dist * 2.0) else max(dist, dist_ee) if use_envelope else dist
```

**Issue:** The nested ternary `A if cond1 else B if cond2 else C` is ambiguous in Python: it parses as `A if cond1 else (B if cond2 else C)`, which happens to be the intended semantics here. However, a future maintainer might misread this as `(A if cond1 else B) if cond2 else C`, leading to a refactoring bug.

**Failure scenario:** If brackets are added incorrectly during cleanup, the SLOW_DOWN trigger could fire for distant EE positions, causing excessive slowdowns.

**Fix:** Rewrite as an explicit `if/elif/else` block:
```python
if use_envelope and dist_ee < warn_dist * 2.0:
    dist_slow = dist
elif use_envelope:
    dist_slow = max(dist, dist_ee)
else:
    dist_slow = dist
```

---

### P0-2: `rule_engine.py:266-267` — Hardcoded `dt=0.02` instead of using config's `control_dt`

**File:** [source/GMRobot/GMRobot/safety/rule_engine.py:266-267](source/GMRobot/GMRobot/safety/rule_engine.py#L266-L267)

```python
if dt <= cfg.eps:
    dt = 0.02
```

**Issue:** When the time delta between steps is zero or negative, the code hardcodes `dt = 0.02` (50 Hz). But `cfg.control_dt` is also 0.02 by default and could be configured differently via YAML. Using a hardcoded value when the config specifies a different `control_dt` would produce inconsistent forecast rates.

**Failure scenario:** A user sets `control_frequency: 100` (dt=0.01) in their YAML config. On the first call or when `sim_time` doesn't advance, the forecast rate uses `0.02` instead of `0.01`, producing a ~2× error in `dist_min_slope_rate` and `ttc_forecast_s`.

**Fix:** Replace `0.02` with `cfg.control_dt`:
```python
if dt <= cfg.eps:
    dt = cfg.control_dt
```

---

## P1 — Wrong Result

### P1-1: `fusion.py:179` — `_is_tier1_eligible` treats empty `trigger_rule` as eligible for Tier1 override

**File:** [source/GMRobot/GMRobot/safety/fusion.py:179](source/GMRobot/GMRobot/safety/fusion.py#L179)

```python
if trigger_rule not in ("static", "", "allow"):
    return False
```

**Issue:** An empty string `""` trigger_rule passes the eligibility check. While in normal operation the RuleEngine always sets `trigger_rule` (to "static", "ttc", "workspace", "held_critical", "functional", "static_far"), if a GateResult is constructed manually or arrives from a different code path with an empty `trigger_rule`, a non-static STOP (e.g., from TTC or workspace violation) would be incorrectly treated as eligible for ML downgrade to ALLOW.

**Failure scenario:** A test fixture or replay script constructs a GateResult with `g_t=STOP` and `trigger_rule=""`. The fusion logic downgrades this STOP to ALLOW because the ML predictor returns ALLOW, despite the STOP having nothing to do with `static` distance rules.

**Fix:** Change `""` to only match when we're sure:
```python
if trigger_rule not in ("static", "allow"):
    return False
```
Or add explicit handling: only treat `""` as static-eligible when `g_rule == STOP` and the STOP was clearly from a distance-based rule.

---

### P1-2: `fusion.py:113-114` — Tier0 check uses `tier0_dist < safe_dist_hard_stop` but `tier0_dist` could be `dist_min_envelope` while EE distance is larger

**File:** [source/GMRobot/GMRobot/safety/fusion.py:110-113](source/GMRobot/GMRobot/safety/fusion.py#L110-L113)

```python
# Tier0: hard collision envelope — never overridden by ML.
if tier0_dist is not None and float(tier0_dist) < safe_dist_hard_stop:
    return _STOP, 0
```

**Issue:** When `envelope_gating=True`, `tier0_dist` is `dist_min_envelope` (the smallest gap between any robot primitive and the hand). But `safe_dist_hard_stop=0.13` was calibrated for EE-to-hand distance, not full-envelope min distance. When the arm elbow passes near the hand at 0.10m while EE is at 0.30m, Tier0 triggers STOP. The rule_engine has similar logic at line 110 (`not (use_envelope and dist_ee >= warn_dist)`) but the fusion module's Tier0 has no such guard — it always fires regardless of EE distance.

**Failure scenario:** During a transit where an arm link swings near the human hand (0.10m) but the EE gripper is 0.35m away: Tier0 fires non-overridable STOP. The rule_engine at the same step would NOT fire STOP because of its `dist_ee >= warn_dist` guard (line 110). This creates an inconsistency: fusion says STOP, rule_engine says ALLOW/SLOW_DOWN.

**Fix:** Add the same guard as rule_engine in Tier0:
```python
if tier0_dist is not None and float(tier0_dist) < safe_dist_hard_stop:
    if not (envelope_gating and dist_ee_human is not None and float(dist_ee_human) >= safe_dist_warn):
        return _STOP, 0
```

---

### P1-3: `rule_engine.py:110` — `dist_ee >= warn_dist` guard suppresses STOP even when arm link is inside hard_stop

**File:** [source/GMRobot/GMRobot/safety/rule_engine.py:108-110](source/GMRobot/GMRobot/safety/rule_engine.py#L108-L110)

```python
elif dist_hard < hard_stop:
    # 2.5b: 包络进 Tier0 但 EE 仍远 → 不提前后退
    if not (use_envelope and dist_ee >= warn_dist):
        decisions.append((GateDecision.STOP, ...))
```

**Issue:** This suppression is the mirror of P1-2. When `use_envelope=True` and `dist_ee >= warn_dist`, a `dist_min_envelope < hard_stop` is deliberately ignored. The comment justifies this as avoiding over-conservative stopping ("user sees EE is far from hand, stopping seems over-reactive"). However, the envelope primitives include arm links, and an arm elbow inside 0.13m of the hand is a genuine collision risk regardless of where the EE is.

**Failure scenario:** During a pick motion, the forearm link passes within 0.08m of the human hand while EE is 0.25m away reaching toward a bin. The rule engine silently allows the motion. If the human hand moves slightly, actual contact occurs on the forearm — not the EE — and there was no STOP.

**Fix:** Consider using a separate, larger `safe_dist_hard_stop_envelope` for envelope gating, or only suppress when the closest primitive is the EE/held box (not an arm link):
```python
if not (use_envelope and dist_ee >= warn_dist and closest_primitive_group != "arm"):
```

---

### P1-4: `replan/triggers.py:388-397` — TTC STOP conflated with SLOW_DOWN for forecast replan when carrying

**File:** [source/GMRobot/GMRobot/safety/replan/triggers.py:388-397](source/GMRobot/GMRobot/safety/replan/triggers.py#L388-L397)

```python
if (
    not gate_ok
    and gate_result.g_t == GateDecision.STOP
    and trigger_rule == "ttc"
    and self.config.held_critical_replan_enabled
    and gate_result.metadata.get("dist_min_held") not in (None, "")
):
    gate_ok = True
```

**Issue:** When `held_critical_replan_enabled=True` and a TTC STOP fires while carrying a part, the forecast early trigger treats this as `gate_ok = True`. This means it will attempt a `ttc_forecast` replan even though the current gate decision is a hard STOP. The replan trigger at lines 184-187 explicitly returns None for hard STOP (unless it's a held_critical STOP). But the forecast path bypasses this guard.

**Failure scenario:** Hand approaches fast (TTC < 0.5s → STOP) while robot is carrying a part. The forecast trigger fires a `ttc_forecast` replan (even though the current decision is STOP). The detour splice is injected while STOP is active, potentially creating conflicting motion commands.

**Fix:** Only allow forecast early trigger when the gate is SLOW_DOWN (not STOP):
```python
# Remove the special case that promotes STOP to gate_ok.
# Forecast replan should only fire from SLOW_DOWN state.
```

---

### P1-5: `replan/executor.py:67-87` — `poll()` returns synthetic ReplanResult without any async processing

**File:** [source/GMRobot/GMRobot/safety/replan/executor.py:67-87](source/GMRobot/GMRobot/safety/replan/executor.py#L67-L87)

```python
def poll(self) -> ReplanResult | None:
    if self._completed:
        _, result = self._completed.popleft()
        return result
    if not self._pending:
        return None
    request = self._pending.popleft()
    t0 = time.monotonic()
    advance_until = request.task_time_step + 3 * MAX_DETOUR_STAGE_DURATION
    result = ReplanResult(status="success", ...)
    ...
    return result
```

**Issue:** The `poll()` method claims to be non-blocking async, and the `MotionReplanExecutor` ABC documents "非阻塞取已完成结果" (non-blocking fetch of completed results). But the implementation pops a pending request and immediately returns a synthetic `ReplanResult(status="success")` without any computation. The actual detour computation happens later in `apply()`. If `apply()` fails, there's no way to signal the failure back through the poll/result path — the result was already returned as "success."

**Failure scenario:** `poll()` returns `status="success"`. Caller assumes the replan trajectory has been computed and is ready. But `apply()` later fails because `splice_replan_detour()` returns False (e.g., no headroom). The caller has already advanced its state based on the successful poll.

**Fix:** Either:
1. Perform the `splice_replan_detour` computation inside `poll()` (making it synchronous), or
2. Return `status="pending"` from `poll()` for requests that still need `apply()`, and only return `"success"` after `apply()` succeeds.

---

### P1-6: `config.py:540-541` — Legacy compat path silently collapses hard_stop and warn to same value

**File:** [source/GMRobot/GMRobot/safety/config.py:540-541](source/GMRobot/GMRobot/safety/config.py#L540-L541)

```python
if hard_stop_raw is None and warn_raw is None and "safe_dist_static" in data:
    safe_dist_hard_stop = safe_dist_static
    safe_dist_warn = safe_dist_static
```

**Issue:** When only `safe_dist_static` is provided (legacy config), both `safe_dist_hard_stop` and `safe_dist_warn` are set to the same value. This effectively disables the SLOW_DOWN warn band — every violation becomes a hard STOP. The test at [tests/test_rule_engine.py:60-66](tests/test_rule_engine.py#L60-L66) confirms this behavior. While intentional for backward compatibility, this is a silent behavior change that could surprise users upgrading configs.

**Failure scenario:** A user copies an old config with `safe_dist_static: 0.25`. They expect both STOP and SLOW_DOWN bands, but get STOP-only. The system becomes much more conservative without any warning.

**Fix:** Emit a warning when collapsing:
```python
import warnings
if hard_stop_raw is None and warn_raw is None and "safe_dist_static" in data:
    warnings.warn(
        "safe_dist_static is deprecated; set safe_dist_hard_stop and safe_dist_warn explicitly. "
        "Falling back to STOP-only (no SLOW_DOWN band)."
    )
    safe_dist_hard_stop = safe_dist_static
    safe_dist_warn = safe_dist_static
```

---

### P1-7: `hand_trajectory_filter.py:250-262` — Prediction field mapping hardcoded to default horizons

**File:** [source/GMRobot/GMRobot/safety/hand_trajectory_filter.py:250-262](source/GMRobot/GMRobot/safety/hand_trajectory_filter.py#L250-L262)

```python
if len(horizons) >= 1 and horizons[0] > 0:
    result = self.predict_at_with_uncertainty(horizons[0])
    if result is not None:
        pred.predicted_pos_at_0_2s, pred.uncertainty_0_2s = result
if len(horizons) >= 2 and horizons[1] > 0:
    result = self.predict_at_with_uncertainty(horizons[1])
    ...
```

**Issue:** The field names `predicted_pos_at_0_2s`, `predicted_pos_at_0_5s`, `predicted_pos_at_1_0s` assume specific horizons. If a user changes `prediction_horizons_s` to `[0.3, 0.8]`, index 0 maps to the `at_0_2s` field (wrong: it's actually 0.3s) and index 1 maps to `at_0_5s` (wrong: it's actually 0.8s). The field names become semantically incorrect.

**Fix:** Use generic field names or attach the horizon value to each prediction.

---

### P1-8: `replan/route_conflict.py:213-214` — Artificially inflates g_rule from ALLOW to SLOW_DOWN in replan request

**File:** [source/GMRobot/GMRobot/safety/replan/route_conflict.py:213-214](source/GMRobot/GMRobot/safety/replan/route_conflict.py#L213-L214)

```python
if conflict.min_gap_m < hard_gap_m and g_rule == int(GateDecision.ALLOW):
    g_rule = int(GateDecision.SLOW_DOWN)
```

**Issue:** When the forecast route conflict predicts a future gap below `hard_gap_m`, the code overwrites the current gate decision (`ALLOW`) to `SLOW_DOWN` in the ReplanRequest. This conflates the current state with a predicted future state. Callers of the ReplanRequest see `g_rule=SLOW_DOWN` and may act as if the gate had already issued SLOW_DOWN, when in fact the gate is currently ALLOW.

**Failure scenario:** A shadow logger or metrics collector reads the ReplanRequest and records "SLOW_DOWN triggered at step N", when actually the gate was ALLOW at step N. Metrics become inflated.

**Fix:** Keep `g_rule` as the actual current gate decision and add a separate field for the forecast severity:
```python
forecast_severity = int(GateDecision.SLOW_DOWN) if conflict.min_gap_m < hard_gap_m else int(gate_result.g_t)
```

---

## P2 — Edge Cases / Robustness

### P2-1: `rule_engine.py` — Instance state (`_prev_dist_min`, `_prev_sim_time`) shared across environments

**File:** [source/GMRobot/GMRobot/safety/rule_engine.py:18-19](source/GMRobot/GMRobot/safety/rule_engine.py#L18-L19)

```python
self._prev_dist_min: float | None = None
self._prev_sim_time: float | None = None
```

**Issue:** If the same `RuleEngine` instance is used across multiple parallel environments (vectorized Isaac Sim), the `_prev_dist_min` and `_prev_sim_time` from one environment would contaminate the forecast computation for another. The reset at `step_index == 0` (line 71) helps but doesn't cover mid-episode env switches.

**Failure scenario:** Two vectorized environments share one RuleEngine. Env A's hand moves toward the robot (decreasing dist), env B's hand moves away. The `_prev_dist_min` state from env A causes env B's forecast rate to show false approach, triggering unnecessary replan.

**Fix:** Make state per-environment (dict keyed by env_index) or document that RuleEngine instances must not be shared.

---

### P2-2: `metrics.py` — Instance state shared across environments

**File:** [source/GMRobot/GMRobot/safety/metrics.py:18](source/GMRobot/GMRobot/safety/metrics.py#L18)

Same issue as P2-1: `_current_stop_run`, `_replan_applied_this_episode` are instance-level and would be corrupted in multi-env use.

---

### P2-3: `logger.py:302` — `_pending_rows` accumulates unbounded memory before flush

**File:** [source/GMRobot/GMRobot/safety/logger.py:302](source/GMRobot/GMRobot/safety/logger.py#L302)

```python
self._pending_rows: list[dict[str, Any]] = []
```

**Issue:** Rows accumulate in memory and are only flushed every `flush_interval` (default 50) steps. For very long episodes (10,000+ steps) with many fields per row, this is fine. But the `_patch_outcome_if_needed` method (line 518) reads the entire CSV back into memory, doubling peak memory. For episodes with 100k+ steps, this could cause OOM.

**Fix:** Stream the patch or use a tempfile approach for outcome patching.

---

### P2-4: `logger.py:510` — `_writer` fieldnames frozen to first row's keys

**File:** [source/GMRobot/GMRobot/safety/logger.py:507-510](source/GMRobot/GMRobot/safety/logger.py#L507-L510)

```python
if self._writer is None:
    self._fieldnames = list(serialized.keys())
    self._writer = csv.DictWriter(self._csv_file, fieldnames=self._fieldnames)
```

**Issue:** The CSV header is determined by the keys of the first row. If the first row doesn't include optional fields (e.g., `g_ground_truth`, `gt_branch_fields`, envelope fields because they weren't provided yet), but later rows do, `DictWriter` would raise a ValueError. In practice this is avoided because all reserved columns are always present in every row (lines 378-386). But if a new contributor adds a column without adding it to the reserved dicts, the CSV would break mid-episode.

**Fix:** Pre-declare the complete fieldnames list from all known column key tuples instead of inferring from the first row.

---

### P2-5: `part_tracker.py:258-259` — `success_rate` denominator excludes in-transit parts

**File:** [source/GMRobot/GMRobot/safety/part_tracker.py:258-259](source/GMRobot/GMRobot/safety/part_tracker.py#L258-L259)

```python
total_attempted = placed_count + len(dropped) + len(skipped)
success_rate = placed_count / max(total_attempted, 1)
```

**Issue:** Parts still in transit at episode end are not counted as attempted, inflating the success rate. If an episode times out with 10 parts in transit, 5 placed, and 5 dropped, the reported rate is 5/(5+5) = 50% when it should be 5/20 = 25%.

**Fix:** Include in_transit in the attempted count or report two rates (placed/attempted and placed/total).

---

### P2-6: `types.py:78-79` — `from_runtime` falls back to finite-difference EE velocity when `ee_vel` near zero

**File:** [source/GMRobot/GMRobot/safety/types.py:78-79](source/GMRobot/GMRobot/safety/types.py#L78-L79)

```python
if prev_ee_pos is not None and np.linalg.norm(ee_vel) < 1e-9:
    ee_vel = (ee_pos - np.asarray(prev_ee_pos, dtype=np.float64)[:3]) / control_dt
```

**Issue:** Uses `np.linalg.norm(ee_vel) < 1e-9` to detect zero velocity. But if `ee_vel` is genuinely near-zero (robot holding still) AND `prev_ee_pos` is provided, it recalculates velocity as `(current_pos - prev_pos) / dt`. For a stationary robot, the finite difference should also be near-zero, so this should be fine. But if `ee_vel` is reported as zeros by the sim but the robot actually moved (sensor glitch), this fallback silently corrects it. Conversely, if `ee_vel` is correct but very small (robot moving at 0.5 mm/s), this unnecessarily recalculates. Low risk.

---

### P2-7: `envelope.py:231` — Deferred import of `scipy.spatial.transform` inside `build_primitives`

**File:** [source/GMRobot/GMRobot/safety/envelope.py:231](source/GMRobot/GMRobot/safety/envelope.py#L231)

```python
from scipy.spatial.transform import Rotation as _R
```

**Issue:** Import inside a method is a deferred import pattern that can fail at runtime if scipy is not installed. The comment says this path is only reached at runtime with a held_part_pose, but there's no try/except or informative error message if scipy is missing.

**Fix:** Either move to top-level import with a try/except that provides a clear error, or add an inline try/except:
```python
try:
    from scipy.spatial.transform import Rotation as _R
except ImportError:
    raise ImportError(
        "scipy is required for held-part pose envelope computation. "
        "Install with: pip install scipy"
    )
```

---

### P2-8: `replan/triggers.py:140-142` — `dist` resolution falls through `dist_ee_human` as legacy fallback

**File:** [source/GMRobot/GMRobot/safety/replan/triggers.py:134-142](source/GMRobot/GMRobot/safety/replan/triggers.py#L134-L142)

```python
dist = gate_result.metadata.get("dist_min_envelope")
if dist is None:
    dist = gate_result.metadata.get("dist_min")
if dist is None:
    dist = gate_result.metadata.get("dist_ee_human")
```

**Issue:** When envelope gating is active but `dist_min_envelope` is missing from metadata (e.g., old log replay), the trigger falls back to `dist_ee_human`. This value is semantically different (point-to-point vs envelope min) and would cause the trigger to use wrong thresholds. The comment acknowledges this as "Legacy fallback" but doesn't warn.

**Fix:** Log a warning when falling back to `dist_ee_human` in envelope mode.

---

### P2-9: `replan/strategy.py:284` — `max(scores, key=scores.get)` is non-deterministic on ties

**File:** [source/GMRobot/GMRobot/safety/replan/strategy.py:284](source/GMRobot/GMRobot/safety/replan/strategy.py#L284)

```python
best = max(scores, key=scores.get)
```

**Issue:** When two strategies have the exact same score, `max()` returns the first one encountered in dict iteration order (Python 3.7+: insertion order). The insertion order is RAISE_THEN_LATERAL, LATERAL_FIRST, RETREAT_THEN_ARC. In case of a tie, RAISE_THEN_LATERAL always wins, which may or may not be the desired tiebreaker. This is deterministic but not explicitly chosen.

**Fix:** Document the tiebreaker preference or add explicit tiebreaking logic.

---

### P2-10: `fusion_draft.py:30-38` — `max_severity` returns `_ALLOW` when given no decisions

**File:** [source/GMRobot/GMRobot/safety/fusion_draft.py:30-38](source/GMRobot/GMRobot/safety/fusion_draft.py#L30-L38)

```python
def max_severity(*decisions: int) -> int:
    best = _ALLOW
    best_rank = -1
    for d in decisions:
        rank = _SEVERITY.get(int(d), 0)
        if rank > best_rank:
            best_rank = rank
            best = int(d)
    return best
```

**Issue:** If called with no arguments (`max_severity()`), returns `_ALLOW` (0). While not currently called this way, it's an implicit default that could mask bugs where a caller accidentally passes zero arguments. The `_SEVERITY.get(int(d), 0)` also silently maps unknown values to ALLOW severity (rank 0), which could hide data corruption.

**Fix:** Raise ValueError on empty input, and warn on unknown severity values:
```python
def max_severity(*decisions: int) -> int:
    if not decisions:
        raise ValueError("max_severity requires at least one decision")
    ...
    rank = _SEVERITY.get(int(d))
    if rank is None:
        raise ValueError(f"Unknown gate decision: {d}")
```

---

## Test Coverage Gaps

### Key Untested Code Paths

| Module | Untested Path | Risk |
|--------|--------------|------|
| `rule_engine.py` | Envelope gating branch (`use_envelope=True`) | P1 — Complex logic with `dist_slow` ternary, `dist_ee >= warn_dist` guard |
| `rule_engine.py` | `held_critical` STOP (dist_min_held < 0.10m) | P1 — No test verifies held-object critical stop triggers correctly |
| `rule_engine.py` | `functional_risk_info` (rewind count, release zone) | P2 — Untested functional safety rules |
| `rule_engine.py` | `static_far` SLOW_DOWN trigger | P2 — Option A untested |
| `rule_engine.py` | `ttc_dist_source="ee"` branch | P2 — Untested TTC distance source switching |
| `rule_engine.py` | `closest_primitive_pos` in TTC | P1 — S7 Option C untested |
| `rule_engine.py` | `skip_ttc=True` | P2 — Vertical lift TTC skip untested |
| `fusion.py` | `envelope_gating=True` in `compute_tier_fusion` | P1 — P1-2 above |
| `fusion.py` | `g_ml_confidence < theta` overrides low-conf STOP | Covered in tests ✓ |
| `fusion.py` | `trigger_rule="static" and dist_ee_human > safe_dist_warn` | P2 — Static stress band override |
| `fusion_draft.py` | `g_ground_truth=STOP` → `tier0_gt_would_stop` | P2 |
| `envelope.py` | `held_part_pose` with scipy Rotation (3-segment box) | P1 — Untested scipy code path |
| `envelope.py` | Interpolation spheres between arm links (D3) | P2 |
| `envelope.py` | Torso primitive addition (W17) | P2 |
| `hand_trajectory_filter.py` | Kalman filter update + predict cycle | P1 — Entire module has no dedicated tests |
| `hand_trajectory_filter.py` | 2D observation fusion (`update_2d`) | P1 — Untested |
| `hand_trajectory_filter.py` | Joseph-form covariance numerical stability | P2 |
| `replan/triggers.py` | Full trigger → replan request flow | P1 — Complex logic with many gates |
| `replan/triggers.py` | `_proactive_route_replan` path | P1 — Untested |
| `replan/triggers.py` | `_forecast_early_trigger` | P2 — Shadow forecast trigger |
| `replan/route_conflict.py` | `evaluate_route_conflict` with carrying path | P1 — Untested |
| `replan/strategy.py` | `select_detour_strategy` all branches | P1 — Scoring logic untested |
| `replan/executor.py` | `apply()` with `splice_replan_detour` | P1 — Integration with policy |
| `ground_truth.py` | Torso + hand combined GT | P2 |
| `ground_truth.py` | `compute_ground_truth_v12` with custom threshold | P2 |
| `part_tracker.py` | Full lifecycle: pick → transit → place/drop | P1 — Entire module has no dedicated tests |
| `part_tracker.py` | Rewind count → SKIPPED transition | P2 |
| `logger.py` | End-to-end CSV round-trip verification | P2 |
| `config.py` | `from_dict` with YAML base inheritance | P2 |

### Missing Integration Tests

1. **RuleEngine → SafetyGate chain:** Test that STOP produces `prev_action`, SLOW_DOWN blends correctly, ALLOW passes through.
2. **EnvelopeEvaluator → RuleEngine chain:** Test that envelope distances flow through to correct gate decisions.
3. **Replan trigger → executor → policy splice:** End-to-end replan test.
4. **Fusion: rule_engine output → `compute_fusion`:** Integration of Layer 1 + Layer 2 decisions.
5. **Logger: record → flush → read back:** Verify CSV round-trip fidelity.

---

## Positive Findings (Things Done Well)

1. **Tier0 hard stop is truly non-overridable** — ML can never downgrade a Tier0 collision. This is the right safety architecture.

2. **Joseph-form covariance update** in Kalman filter ensures numerical stability of the state covariance matrix.

3. **Regularized matrix inverse** (`_eps = np.eye(S.shape[0]) * 1e-8`) prevents singular matrix errors in the Kalman update.

4. **Comprehensive metadata propagation** — every gate decision carries rich metadata (`dist_ee_human`, `ttc`, `approach_rate`, `trigger_rule`, `slow_down_alpha`) that enables downstream observability.

5. **Deep-merge YAML config inheritance** (`_deep_merge_dicts` + `base` key) allows clean scenario composition without duplication.

6. **Forward-fill pattern** for perception/VLM fields in the logger (last known values carried forward) is appropriate for sparse async sensor data.

7. **Cooldown mechanism** in replan trigger prevents replan thrashing (200-step cooldown + same-task-step dedup).

8. **All reserved CSV columns are always present** — prevents DictWriter key errors when optional fields appear mid-episode.

9. **Clear dataclass design** — separation of config, runtime state, and result types. Immutable where appropriate (`frozen=True` on configs and results).

10. **`surface_gap_sphere` correctly handles sphere-sphere distance** with `max(0.0, center_dist - r1 - r2)` — never returns negative gaps.

---

## Recommendations

### Before Paper Submission (P0 + P1)

1. **Fix P0-2** (hardcoded dt) — one-line change.
2. **Fix P1-1** (empty trigger_rule in fusion) — tighten the eligibility check.
3. **Fix P1-2** (Tier0 fires on arm links when EE is far) — add the same guard as rule_engine.
4. **Fix P1-5** (poll/apply contract mismatch) — make the executor contract honest.
5. **Fix P1-6** (silent legacy config collapse) — add deprecation warning.

### Before Long-Running Experiments (P2)

6. **P2-1/P2-2** — Document single-env-only constraint or add per-env state dicts.
7. **P2-7** — Add try/except for scipy import.
8. **P2-9** — Document tiebreaker behavior in strategy selector.

### Test Investment

9. Add 8–12 new test cases covering the untested paths listed above, prioritizing:
   - Envelope gating in rule_engine (highest risk)
   - Held-critical STOP trigger
   - Kalman filter update/predict cycle
   - Replan trigger → executor integration
   - Part tracker lifecycle

---

*Report generated by automated multi-dimensional code review. Each finding was verified against source code at the referenced lines. See [CODE_REVIEW_REPORT_2026-07-01.md](CODE_REVIEW_REPORT_2026-07-01.md) for the full report.*
