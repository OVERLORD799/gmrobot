"""BatchTestRunner — programmatic multi-episode batch testing API.

Runs one or more YAML scenario configs through ``scripts/run_phase3.py``,
collects per-episode metrics, and generates comparison reports.

Usage::

    runner = BatchTestRunner("batch_test_configs/", output_dir="results/")
    summary = runner.run_all()
    print(runner.generate_comparison_report())

    # Or run a single config programmatically:
    ep = runner.run_single("batch_test_configs/safety_comparison.yaml")
    print(f"knock_off_rate={ep.knock_off_rate:.2f}")

The runner spawns each episode in a subprocess (fresh Isaac Lab env per
episode — no state leakage).  Metrics are parsed from the per-episode CSV
written by ``run_phase3.py``.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from paths import GMDISTURB_ROOT, PHASE3_SCRIPT, ISAACLAB_ROOT, CONDA_PREFIX, GMROBOT_ROOT, resolve_python

# Repo-relative results directory (per §5.1.6 of paper-demo plan).
_DEFAULT_RESULTS_DIR = os.path.join(GMDISTURB_ROOT, "results", "paper_demo")


# ---------------------------------------------------------------------------
# Episode result
# ---------------------------------------------------------------------------

@dataclass
class EpisodeResult:
    """Parsed metrics from a single episode run."""
    config_name: str
    run_id: str
    success: bool = False
    g1_fell: bool = False
    total_steps: int = 0
    policy_steps: int = 0
    parts_placed: int = 0
    parts_total: int = 20
    tier0_stop_count: int = 0
    slowdown_count: int = 0
    replan_count: int = 0
    stuck_count: int = 0
    d_stop_caused: int = 0
    d_slow_caused: int = 0
    d_replan_caused: int = 0
    d_knock_off: int = 0
    footstep_count: int = 0
    collision_count: int = 0
    object_drop_count: int = 0
    min_distance_m: float = float("inf")
    min_surface_distance_m: float = float("inf")
    mean_distance_m: float = 0.0
    f_consecutive_stop_max: int = 0
    h_vlm_action: str = ""
    h_vlm_latency_ms: float = 0.0
    elapsed_s: float = 0.0
    csv_path: str = ""
    raw_error: str = ""
    # ---- New disturbance attribution fields (§6.1) ----
    disturbance_source: str = ""       # none|g1_body|g1_physical_hand_*|g1_attached_proxy|scripted_virtual_hand
    disturbance_scenario: str = ""
    disturbance_attempts: int = 0      # unique attempt IDs during episode
    gate_trigger_source: str = ""      # which source triggered the safety gate
    replan_trigger_source: str = ""    # which source triggered replan
    # ---- Subprocess validation (§5.1.5) ----
    subprocess_validated: bool = False
    subprocess_validation_errors: str = ""
    # ---- Scenario auto-verdict (§6.2-6.3) ----
    scenario_pass: bool | None = None       # None = not evaluated
    scenario_failure_reasons: str = ""
    attributed_stop_attempts: int = 0
    attributed_slow_attempts: int = 0
    attributed_replan_attempts: int = 0
    progress_after_retreat: bool = False     # policy time advanced after last retreat
    # ---- B2 / B4-Dynamic ----
    safety_enforcement_mode: str = "active"
    disturbance_trajectory_id: str = ""
    pre_hard_stop_replan_count: int = 0
    held_critical_replan_count: int = 0
    shadow_stop_would_count: int = 0
    shadow_slow_would_count: int = 0
    shadow_replan_would_count: int = 0
    shadow_nonallow_evaluated_steps: int = 0
    shadow_clock_blocked_steps: int = 0
    shadow_action_modified_steps: int = 0
    shadow_replan_applied_count: int = 0
    shadow_retreat_count: int = 0
    b2_proactive_trigger_count: int = 0
    proxy_physical_contact_count: int = 0
    # ---- Recovery / audit (B2) ----
    retreat_attempt_count: int = 0
    recovered_attempt_count: int = 0
    recovery_pairing_ok: bool = True
    recovery_pairing_summary: str = ""
    events_csv_valid: bool = True
    events_csv_errors: str = ""
    max_trigger_apply_latency: int = -1
    # ---- Extended metrics ----
    closest_g1_body: str = ""
    dist_min_g1_body: float = float("inf")
    dist_min_proxy: float = float("inf")

    # Derived
    @property
    def knock_off_rate(self) -> float:
        return self.d_knock_off / max(self.parts_total, 1)

    @property
    def intervention_rate(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.tier0_stop_count + self.slowdown_count) / self.total_steps

    @property
    def is_livelock(self) -> bool:
        return self.f_consecutive_stop_max > 100


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class BatchTestRunner:
    """Runs multiple test configurations and aggregates results.

    Each config is a YAML file with scenario + safety settings (see
    ``SCENARIOS.md`` for the schema).  One episode is run per config
    (or N repeats if ``repeat`` is set in the config YAML).

    Parameters
    ----------
    config_dir:
        Directory containing YAML scenario config files.
    output_dir:
        Directory for per-episode CSVs, JSONL summary, and comparison report.
    """

    _PROJ_ROOT = GMDISTURB_ROOT
    _PHASE3 = PHASE3_SCRIPT
    _ISAAC_LAB = ISAACLAB_ROOT
    _PYTHON = resolve_python()

    def __init__(self, config_dir: str, output_dir: str = _DEFAULT_RESULTS_DIR):
        self.config_dir = Path(config_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._results: list[EpisodeResult] = []

    def _list_yaml_configs(self) -> list[Path]:
        """Return YAML configs from a file or directory path (P0-3)."""
        p = self.config_dir
        if p.is_file():
            if p.suffix.lower() not in (".yaml", ".yml"):
                raise ValueError(f"Not a YAML config file: {p}")
            return [p.resolve()]
        if p.is_dir():
            files = sorted(p.glob("*.yaml")) + sorted(p.glob("*.yml"))
            if not files:
                raise FileNotFoundError(f"No YAML configs found in {p}")
            return files
        raise FileNotFoundError(f"Config path not found: {p}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self, *, max_parallel: int = 1, timeout_s: int = 3600) -> dict:
        """Run all YAML configs in *config_dir*, return aggregated summary.

        Each YAML may specify ``repeat`` (default 1) for multi-seed runs.
        The YAML ``seed`` is used as the base seed; each repeat increments by 1.

        Parameters
        ----------
        max_parallel:
            Maximum concurrent episodes (1 = sequential).
        timeout_s:
            Per-episode timeout in seconds.

        Returns
        -------
        dict with keys ``runs`` (list of EpisodeResult dicts) and
        ``comparison_table`` (list of dicts, one per config).
        """
        import yaml

        yaml_files = self._list_yaml_configs()

        print(f"[batch_runner] {len(yaml_files)} config(s) in {self.config_dir}")
        for yf in yaml_files:
            # Read repeat count from the YAML before running.
            with open(yf) as fh:
                _ycfg = yaml.safe_load(fh) or {}
            _repeat = int(_ycfg.get("repeat", 1))
            _base_seed = _ycfg.get("seed")
            for _rep_idx in range(_repeat):
                _seed = (_base_seed + _rep_idx) if isinstance(_base_seed, int) else None
                result = self.run_single(str(yf), timeout_s=timeout_s,
                                         force_seed=_seed, repeat_idx=_rep_idx)
                self._results.append(result)

        self.save_batch_summary()
        comparison = self._build_comparison_table()
        return {
            "runs": [r.__dict__ for r in self._results],
            "comparison_table": comparison,
        }

    def run_single(self, config_path: str, *, timeout_s: int = 3600,
                    force_seed: int | None = None, repeat_idx: int = 0) -> EpisodeResult:
        """Run a single test configuration.

        Spawns ``run_phase3.py`` in a subprocess with the config's parameters.
        Parses the resulting CSV for metrics.

        Parameters
        ----------
        config_path:
            Path to a YAML scenario config file.
        timeout_s:
            Episode timeout in seconds.
        force_seed:
            Override seed from run_all() multi-repeat loop.
        repeat_idx:
            Zero-based repeat index (used for run_id disambiguation).

        Returns
        -------
        :class:`EpisodeResult` for this run.
        """
        import yaml

        _yaml_path = str(Path(config_path).resolve())  # absolute path for subprocess (cwd ≠ project root)
        config_name = Path(_yaml_path).stem

        with open(_yaml_path) as f:
            cfg = yaml.safe_load(f) or {}

        # Build CLI args from YAML config.
        # scenario = YAML field for CLI --scenario (separate from name used as run id)
        scenario = cfg.get("scenario", cfg.get("name", config_name))
        mode = cfg.get("mode", "constrained_wander")
        safety_cfg = cfg.get("safety", {})
        safety_config_path = safety_cfg.get("config_path", "")
        episode_cfg = cfg.get("episode", {})
        max_steps = episode_cfg.get("max_steps", 10000)
        enable_vlm = cfg.get("sensors", {}).get("enable_head_camera", False)
        enable_replan = safety_cfg.get("enable_replan", False)
        virtual_hand_cfg = cfg.get("virtual_hand", {})
        virtual_hand_radius = (
            virtual_hand_cfg.get("reach_radius")
            or virtual_hand_cfg.get("radius")
            or virtual_hand_cfg.get("default_radius")
        )
        virtual_hand_speed = virtual_hand_cfg.get("speed", None)
        # H1 fix (2026-07-13): wire previously-missing CLI args from YAML.
        approach_side = cfg.get("approach_side")
        headless = cfg.get("headless", False)
        vhand_lag = virtual_hand_cfg.get("lag")
        vhand_retreat = virtual_hand_cfg.get("retreat_steps")
        g1_bias_y = cfg.get("g1_bias_y")
        stress = cfg.get("stress", False)
        force_mode = cfg.get("mode_override")
        no_safety = safety_cfg.get("no_safety", False)
        per_part_protocol = cfg.get("per_part_protocol", False)
        dynamic_sweep_enabled = bool((cfg.get("dynamic_sweep") or {}).get("enabled", False))
        enforcement_mode = str(
            (safety_cfg.get("enforcement_mode") or "active")
        ).lower()
        num_parts = episode_cfg.get("num_parts")
        # Seed from YAML — overridden by run_all() repeat loop.
        _seed = force_seed if force_seed is not None else cfg.get("seed")
        # Override config YAML path (separate from the scenario YAML on disk).
        _override_config_yaml = cfg.get("config_path")

        # ---- Derive run_id and per-run directory BEFORE building cmd ----
        _seed_suffix = f"_s{_seed}" if _seed is not None else ""
        _rep_suffix = f"_r{repeat_idx}" if repeat_idx > 0 else ""
        run_id = f"{config_name}{_rep_suffix}{_seed_suffix}_{time.strftime('%H%M%S')}"
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        csv_path = str((run_dir / f"{run_id}.csv").resolve())

        # Build CLI command.  The paper_scenario YAML is passed as --config so
        # config_loader.py reads disturbance.*, virtual_hand.*, etc. from it.
        cmd = [
            self._PYTHON, "-u", self._PHASE3,
            "--max_steps", str(max_steps),
            "--output_csv", csv_path,
            "--config", _yaml_path,   # pass the scenario YAML as config
        ]
        if headless:
            cmd.append("--headless")
        if _override_config_yaml:
            # Additional GMRobot safety config override (rare; prefer scenario YAML).
            pass
        if mode == "scripted" and scenario:
            cmd.extend(["--scenario", scenario])
        elif mode == "vlm_guided":
            cmd.append("--vlm")
        if safety_config_path:
            safety_abs = os.path.join(self._PROJ_ROOT, safety_config_path)
            if not os.path.exists(safety_abs):
                safety_abs = os.path.join(GMROBOT_ROOT, safety_config_path)
            if os.path.exists(safety_abs):
                cmd.extend(["--safety-config", safety_abs])
            else:
                print(f"[batch_runner] WARNING: safety config not found at "
                      f"{self._PROJ_ROOT}/{safety_config_path} or GMRobot root — "
                      f"running WITHOUT --safety-config")
        # H10 fix (2026-07-13): compute a single use_vlm boolean.
        if enable_vlm or mode == "vlm_guided":
            cmd.append("--vlm")
        if enable_replan:
            cmd.append("--replan")
        if virtual_hand_radius is not None:
            cmd.extend(["--virtual-hand", str(virtual_hand_radius)])
        if virtual_hand_speed is not None:
            cmd.extend(["--virtual-hand-speed", str(virtual_hand_speed)])
        if approach_side:
            cmd.extend(["--approach-side", str(approach_side)])
        if vhand_lag is not None:
            cmd.extend(["--vhand-lag", str(vhand_lag)])
        if vhand_retreat is not None:
            cmd.extend(["--vhand-retreat", str(vhand_retreat)])
        if g1_bias_y is not None:
            cmd.extend(["--g1-bias-y", str(g1_bias_y)])
        if stress:
            cmd.append("--stress")
        if force_mode:
            cmd.extend(["--mode", str(force_mode)])
        if no_safety:
            cmd.append("--no-safety")
        if per_part_protocol:
            cmd.append("--per-part-protocol")
        if dynamic_sweep_enabled:
            cmd.append("--dynamic-sweep")
        if enforcement_mode and enforcement_mode != "active":
            cmd.extend(["--enforcement-mode", enforcement_mode])
        if num_parts is not None:
            try:
                _np = int(num_parts)
                if _np > 0:
                    cmd.extend(["--num-parts", str(_np)])
            except (TypeError, ValueError):
                pass
        if _seed is not None:
            cmd.extend(["--seed", str(_seed)])
        # Pass the YAML name as the canonical disturbance scenario label (§6.1).
        _scenario_label = cfg.get("name", config_name)
        if _scenario_label:
            cmd.extend(["--disturbance-scenario-label", str(_scenario_label)])

        t0 = time.monotonic()
        env = os.environ.copy()
        env["CONDA_PREFIX"] = CONDA_PREFIX
        env["OMNI_KIT_ACCEPT_EULA"] = "YES"
        env["DISPLAY"] = os.environ.get("DISPLAY", ":20")

        # Save manifest BEFORE running (YAML snapshot, git revision, versions, seed).
        self._save_manifest(run_dir, run_id, _yaml_path, cfg, cmd,
                            effective_seed=_seed)

        # R6 M2 fix: use cwd= instead of shell=True.  Eliminates command
        # injection surface (YAML config values were spliced into a shell
        # command) and fixes argument splitting for paths with spaces (L4).
        stdout_log = str(run_dir / "stdout.txt")
        stderr_log = str(run_dir / "stderr.txt")
        try:
            with open(stdout_log, "w") as out_f, open(stderr_log, "w") as err_f:
                result = subprocess.run(
                    cmd,
                    cwd=self._ISAAC_LAB,
                    shell=False,
                    env=env,
                    stdout=out_f, stderr=err_f,
                    text=True,
                    timeout=timeout_s,
                )
        except subprocess.TimeoutExpired:
            return EpisodeResult(
                config_name=config_name, run_id=run_id,
                success=False, raw_error="timeout",
                elapsed_s=time.monotonic() - t0,
            )

        elapsed = time.monotonic() - t0
        ep = self._parse_output(config_name, run_id, csv_path, result, elapsed)
        # Run scenario auto-verdict if the YAML defines expected behavior.
        self._evaluate_scenario_verdict(ep, cfg)
        return ep

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_comparison_report(self) -> str:
        """Generate a markdown comparison table across all completed runs.

        Returns
        -------
        str
            Markdown-formatted comparison table.
        """
        table = self._build_comparison_table()
        if not table:
            return "No runs completed."

        header = (
            "| config | verdict | success | attr_STOP | attr_SLOW | attr_REPLAN | "
            "STOP | SLOW | REPLAN | min_dist | livelock | parts |\n"
            "|--------|---------|---------|-----------|-----------|-------------|"
            "------|------|--------|----------|----------|-------|"
        )
        rows = []
        for r in table:
            _verdict = "PASS" if r.get("scenario_pass") else ("FAIL" if r.get("scenario_pass") is False else "—")
            rows.append(
                f"| {r['config']} | {_verdict} | {r['success']} | "
                f"{r.get('attributed_stop_attempts',0)} | {r.get('attributed_slow_attempts',0)} | "
                f"{r.get('attributed_replan_attempts',0)} | "
                f"{r['stop']} | {r['slow']} | {r['replan']} | "
                f"{r['min_dist']:.2f}m | "
                f"{'⚠️' if r['livelock'] else '—'} | "
                f"{r['parts_placed']}/{r['parts_total']} |"
            )
        return header + "\n".join(rows)

    def save_batch_summary(self, path: Optional[str] = None) -> str:
        """Save JSON summary of all runs.

        Parameters
        ----------
        path:
            Output path.  Defaults to ``<output_dir>/batch_summary.json``.

        Returns
        -------
        str
            Path the summary was written to.
        """
        path = path or str(self.output_dir / "batch_summary.json")
        summary = {
            "n_runs": len(self._results),
            "n_success": sum(1 for r in self._results if r.success),
            "n_fell": sum(1 for r in self._results if r.g1_fell),
            "comparison": self._build_comparison_table(),
            "runs": [
                {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
                for r in self._results
            ],
        }
        with open(path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        return path

    # ------------------------------------------------------------------
    # Manifest (§5.1.7)
    # ------------------------------------------------------------------

    @staticmethod
    def _save_manifest(run_dir: Path, run_id: str, config_path: str,
                       cfg: dict, cmd: list[str], *,
                       effective_seed: int | None = None) -> str:
        """Save per-run manifest: config snapshot, command, versions, seed.

        Returns the path to the manifest JSON file.
        """
        import yaml

        manifest: dict = {
            "run_id": run_id,
            "config_source": str(Path(config_path).resolve()),
            "config_yaml_snapshot": cfg,
            "cli_command": " ".join(cmd),
            "seed": effective_seed if effective_seed is not None else cfg.get("seed", "not_specified"),
        }
        _eff = effective_seed if effective_seed is not None else cfg.get("seed")
        if isinstance(_eff, int):
            from seed_utils import seed_manifest, PHYSX_NOTE
            manifest["seeds"] = seed_manifest(
                seed=_eff,
                env_seed=_eff,
                controller_seed=_eff,
                # Virtual hand seed matches when scenario enables --virtual-hand.
                virtual_hand_seed=_eff,
            )
            manifest["physx_reproducibility_note"] = PHYSX_NOTE
        # Record requested G1 spawn from scenario YAML (measured pose is in episode CSV).
        _dist = cfg.get("disturbance") or {}
        if _dist.get("g1_spawn_x") is not None:
            manifest["g1_spawn"] = {
                "g1_spawn_requested_x": _dist.get("g1_spawn_x"),
                "g1_spawn_requested_y": _dist.get("g1_spawn_y", 0.0),
                "g1_spawn_requested_yaw": _dist.get("g1_spawn_yaw", 0.0),
                "g1_spawn_jitter_xy": _dist.get("g1_spawn_jitter_xy", 0.0),
            }

        # Git revision (use GMDISTURB_ROOT which is the monorepo root).
        try:
            import subprocess as _sp
            _git_cwd = str(Path(GMDISTURB_ROOT).parent)  # monorepo root
            git_rev = _sp.run(
                ["git", "rev-parse", "HEAD"],
                cwd=_git_cwd,
                capture_output=True, text=True,
                timeout=5,
            )
            if git_rev.returncode == 0:
                manifest["git_revision"] = git_rev.stdout.strip()
            git_dirty = _sp.run(
                ["git", "diff", "--stat"],
                cwd=_git_cwd,
                capture_output=True, text=True,
                timeout=5,
            )
            manifest["git_dirty"] = bool(git_dirty.stdout.strip())
        except Exception:
            manifest["git_revision"] = "unknown"
            manifest["git_dirty"] = None

        # Python version.
        manifest["python_version"] = sys.version

        # Isaac / driver / GPU versions (best-effort at manifest time).
        try:
            import torch
            manifest["torch_version"] = torch.__version__
            manifest["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                manifest["cuda_version"] = torch.version.cuda
                manifest["gpu_name"] = torch.cuda.get_device_name(0)
        except ImportError:
            pass

        manifest_path = run_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2, default=str)
        return str(manifest_path)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _parse_output(
        self,
        config_name: str,
        run_id: str,
        csv_path: str,
        result: subprocess.CompletedProcess,
        elapsed: float,
    ) -> EpisodeResult:
        """Parse subprocess stdout + CSV into an EpisodeResult.

        Per §5.1.5, validates subprocess success via multiple checks beyond
        just return code.  Stdout/stderr are read from the per-run log files
        written by run_single().
        """
        ep = EpisodeResult(
            config_name=config_name, run_id=run_id,
            success=False, csv_path=csv_path, elapsed_s=elapsed,
        )

        # Read subprocess output from per-run log files.
        run_dir = os.path.dirname(csv_path)
        output = ""
        for log_name in ("stdout.txt", "stderr.txt"):
            log_path = os.path.join(run_dir, log_name)
            if os.path.exists(log_path):
                with open(log_path) as f:
                    output += f.read()
        errors: list[str] = []

        # §5.1.5(a): return code must be 0
        if result.returncode != 0:
            log_err = os.path.join(run_dir, "stderr.txt")
            stderr_content = ""
            if os.path.exists(log_err):
                with open(log_err) as f:
                    stderr_content = f.read()[:500]
            ep.raw_error = stderr_content if stderr_content else f"exit={result.returncode}"
            errors.append(f"non-zero exit code: {result.returncode}")

        # §5.1.5(b): CSV must exist and be non-empty
        if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
            errors.append(f"CSV missing or empty: {csv_path}")
        else:
            # §5.1.5(c): CSV must have expected schema
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    if not rows:
                        errors.append("CSV has header but no data rows")
                    else:
                        expected = {"total_steps", "parts_placed", "episode_id"}
                        actual = set(rows[0].keys())
                        missing = expected - actual
                        if missing:
                            errors.append(f"CSV missing expected columns: {missing}")
                        # §5.1.5(e): at least one simulation step completed
                        if int(rows[-1].get("total_steps", 0)) == 0:
                            errors.append("CSV shows zero simulation steps")
            except Exception as e:
                errors.append(f"CSV parse error: {e}")

        # §5.1.5(d): no fatal errors in logs.
        # Whitelist: "Failed to startup plugin carb.windowing-glfw.plugin" is
        # a harmless headless-mode message from Isaac Sim.  Remove lines
        # containing it before scanning for real failures.
        _filtered_output = "\n".join(
            line for line in output.split("\n")
            if not any(h in line for h in (
                "carb.windowing-glfw.plugin",
                "omni.physx.ui",           # headless — no UI
                "omni.kit.window.drop_support",  # headless — no window
                "omni.kit.menu.utils",     # headless — no menu
            ))
        )
        for keyword in ("Traceback", "ModuleNotFoundError"):
            if keyword in _filtered_output:
                errors.append(f"Found '{keyword}' in subprocess output")
        # "Failed to startup" is only fatal if NOT from the whitelisted GLFW plugin.
        if "Failed to startup" in _filtered_output:
            errors.append("Found 'Failed to startup' in subprocess output")

        # Prefer structured CSV field over log string scanning.
        ep.success = False  # will be set from CSV below
        ep.g1_fell = "G1 collapsed" in output

        # Parse CSV for structured metrics — also append semantic consistency
        # errors here so validation status is decided only after ALL checks.
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
            try:
                with open(csv_path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ep.parts_placed = int(row.get("parts_placed", 0))
                        ep.parts_total = int(row.get("parts_total", ep.parts_total) or ep.parts_total)
                        ep.success = row.get("task_completed", "False") in ("True", "true", "1")
                        if ep.success and ep.parts_placed < ep.parts_total:
                            errors.append(
                                f"Data inconsistency: task_completed=True but "
                                f"parts_placed={ep.parts_placed} < parts_total={ep.parts_total}"
                            )
                        ep.total_steps = int(row.get("total_steps", 0))
                        ep.policy_steps = int(row.get("policy_steps", 0))
                        ep.tier0_stop_count = int(row.get("tier0_stop_count", 0))
                        ep.slowdown_count = int(row.get("slowdown_count", 0))
                        ep.replan_count = int(row.get("replan_count", 0))
                        ep.stuck_count = int(row.get("stuck_count", 0))
                        ep.d_stop_caused = int(row.get("d_stop_caused", 0))
                        ep.d_slow_caused = int(row.get("d_slow_caused", 0))
                        ep.d_replan_caused = int(row.get("d_replan_caused", 0))
                        ep.d_knock_off = int(row.get("d_knock_off", 0))
                        if ep.d_knock_off > ep.parts_total:
                            errors.append(
                                f"Data invalid: d_knock_off={ep.d_knock_off} > "
                                f"parts_total={ep.parts_total}"
                            )
                        ep.object_drop_count = int(row.get("object_drop_count", 0))
                        ep.collision_count = int(row.get("collision_count", 0))
                        ep.footstep_count = int(row.get("footstep_count", 0))
                        ep.f_consecutive_stop_max = int(row.get("f_consecutive_stop_max", 0))
                        ep.h_vlm_action = row.get("h_vlm_action", "")
                        ep.h_vlm_latency_ms = float(row.get("h_vlm_latency_ms", 0) or 0)
                        min_d = row.get("min_g1_ur10e_distance_m", "inf")
                        ep.min_distance_m = float(min_d) if min_d and min_d != "inf" else float("inf")
                        min_s = row.get("min_surface_distance_m", "inf")
                        ep.min_surface_distance_m = float(min_s) if min_s and min_s != "inf" else float("inf")
                        mean_d = row.get("mean_g1_ur10e_distance_m", "0")
                        ep.mean_distance_m = float(mean_d) if mean_d else 0.0
                        # New disturbance attribution fields (§6.1)
                        ep.disturbance_source = row.get("disturbance_source", "")
                        ep.disturbance_scenario = row.get("disturbance_scenario", "")
                        ep.disturbance_attempts = int(row.get("disturbance_attempt_id", 0) or 0)
                        ep.gate_trigger_source = row.get("gate_trigger_source", "")
                        ep.replan_trigger_source = row.get("replan_trigger_source", "")
                        ep.closest_g1_body = row.get("closest_g1_body", "")
                        _dmgb = row.get("dist_min_g1_body", "inf")
                        ep.dist_min_g1_body = float(_dmgb) if _dmgb and _dmgb != "inf" else float("inf")
                        _dmp = row.get("dist_min_proxy", "inf")
                        ep.dist_min_proxy = float(_dmp) if _dmp and _dmp != "inf" else float("inf")
                        ep.progress_after_retreat = row.get("progress_after_retreat", "False") in ("True", "true", "1")
                        ep.safety_enforcement_mode = row.get("safety_enforcement_mode", "active") or "active"
                        ep.disturbance_trajectory_id = row.get("disturbance_trajectory_id", "") or ""
                        ep.pre_hard_stop_replan_count = int(row.get("pre_hard_stop_replan_count", 0) or 0)
                        ep.held_critical_replan_count = int(row.get("held_critical_replan_count", 0) or 0)
                        ep.shadow_stop_would_count = int(row.get("shadow_stop_would_count", 0) or 0)
                        ep.shadow_slow_would_count = int(row.get("shadow_slow_would_count", 0) or 0)
                        ep.shadow_replan_would_count = int(row.get("shadow_replan_would_count", 0) or 0)
                        ep.shadow_nonallow_evaluated_steps = int(
                            row.get("shadow_nonallow_evaluated_steps", 0) or 0
                        )
                        ep.shadow_clock_blocked_steps = int(
                            row.get("shadow_clock_blocked_steps", 0) or 0
                        )
                        ep.shadow_action_modified_steps = int(
                            row.get("shadow_action_modified_steps", 0) or 0
                        )
                        ep.shadow_replan_applied_count = int(
                            row.get("shadow_replan_applied_count", 0) or 0
                        )
                        ep.shadow_retreat_count = int(
                            row.get("shadow_retreat_count", 0) or 0
                        )
                        ep.b2_proactive_trigger_count = int(row.get("b2_proactive_trigger_count", 0) or 0)
                        ep.proxy_physical_contact_count = int(
                            row.get("proxy_physical_contact_count", 0) or 0
                        )
                        ep.retreat_attempt_count = int(
                            row.get("retreat_attempt_count", 0) or 0
                        )
                        ep.recovered_attempt_count = int(
                            row.get("recovered_attempt_count", 0) or 0
                        )
                        # Attempt accounting invariants
                        _retreat_n = int(row.get("retreat_attempt_count", 0) or 0)
                        _recovered_n = int(row.get("recovered_attempt_count", 0) or 0)
                        if _recovered_n > _retreat_n:
                            errors.append(
                                f"Data invalid: recovered_attempt_count={_recovered_n} "
                                f"> retreat_attempt_count={_retreat_n}"
                            )
                        _attempt_id = int(row.get("disturbance_attempt_id", 0) or 0)
                        _parts_tot = int(row.get("parts_total", ep.parts_total) or ep.parts_total)
                        if _parts_tot > 0 and _attempt_id > _parts_tot * 2:
                            errors.append(
                                f"Data invalid: disturbance_attempt_id={_attempt_id} "
                                f"far exceeds parts_total={_parts_tot} "
                                f"(likely double-counted attempts)"
                            )
                        # Proxy hand has no PhysX body — paper field must be 0.
                        # Real mat collisions are NOT zeroed for virtual sources.
                        _proxy_pc = int(row.get("proxy_physical_contact_count", 0) or 0)
                        _src = (row.get("disturbance_source") or "").lower()
                        if ("virtual_hand" in _src or "proxy" in _src) and _proxy_pc != 0:
                            errors.append(
                                f"Data invalid: proxy_physical_contact_count={_proxy_pc} "
                                f"for virtual/proxy source={_src!r} (must be 0)"
                            )
            except Exception as e:
                errors.append(f"CSV parse error: {e}")

        # Sidecar attempts.csv pairing checks (when present).
        _attempts_path = csv_path.replace(".csv", "_attempts.csv")
        if os.path.exists(_attempts_path) and os.path.getsize(_attempts_path) > 0:
            try:
                with open(_attempts_path, newline="") as af:
                    for arow in csv.DictReader(af):
                        recovered = str(arow.get("recovered", "")).lower() in ("true", "1")
                        redeploy = int(arow.get("redeploy_step", -1) or -1)
                        terminal = str(arow.get("terminal_success", "")).lower() in ("true", "1")
                        if recovered and redeploy < 0 and not terminal:
                            errors.append(
                                f"Data invalid: attempt {arow.get('attempt_id')} "
                                f"recovered=True without redeploy_step"
                            )
            except Exception as e:
                errors.append(f"attempts.csv parse error: {e}")

        # Events CSV audit — active B2 vs shadow B4 (P0-6).
        _events_path = csv_path.replace(".csv", "_events.csv")
        if os.path.exists(_events_path) and os.path.getsize(_events_path) > 0:
            try:
                from episode_audit import audit_events_for_episode

                ev_errs, ev_summary = audit_events_for_episode(
                    _events_path,
                    enforcement_mode=ep.safety_enforcement_mode,
                    attempts_path=(
                        _attempts_path if os.path.exists(_attempts_path) else None
                    ),
                )
                ep.events_csv_valid = len(ev_errs) == 0
                ep.events_csv_errors = "; ".join(ev_errs)
                ep.max_trigger_apply_latency = int(
                    ev_summary.get("max_trigger_apply_latency", -1)
                )
                if ep.safety_enforcement_mode.lower() == "shadow":
                    ep.recovery_pairing_summary = (
                        f"shadow_triggers={ev_summary.get('shadow_trigger_count', 0)} "
                        f"applied={ev_summary.get('applied_count', 0)} "
                        f"retreats={ev_summary.get('retreat_count', 0)}"
                    )
                else:
                    ep.recovery_pairing_summary = (
                        f"triggers={ev_summary.get('proactive_trigger_count', 0)} "
                        f"applied={ev_summary.get('applied_count', 0)} "
                        f"retreats={ev_summary.get('retreat_count', 0)}"
                    )
                ep.recovery_pairing_ok = len(ev_errs) == 0
            except Exception as e:
                ep.events_csv_valid = False
                ep.events_csv_errors = str(e)
                ep.recovery_pairing_ok = False
                errors.append(f"events.csv audit error: {e}")
        else:
            ep.events_csv_valid = False
            ep.events_csv_errors = "events CSV missing or empty"
            ep.recovery_pairing_ok = False

        # Finalise validation only after schema, log, and semantic checks.
        ep.subprocess_validated = len(errors) == 0
        ep.subprocess_validation_errors = "; ".join(errors)
        if errors:
            ep.raw_error = f"validation failed: {'; '.join(errors)}"

        return ep

    @staticmethod
    def _evaluate_scenario_verdict(ep: EpisodeResult, cfg: dict) -> None:
        """Evaluate scenario pass/fail based on YAML expected behavior (§6.2-6.3).

        Populates ``ep.scenario_pass``, ``ep.scenario_failure_reasons``,
        and the attributed_* counters.
        """
        scenario_name = cfg.get("name", "")
        if not scenario_name:
            return

        failures: list[str] = []

        # Use strictly deduplicated causal counts from the episode metrics.
        ep.attributed_stop_attempts = ep.d_stop_caused
        ep.attributed_slow_attempts = ep.d_slow_caused
        ep.attributed_replan_attempts = ep.d_replan_caused

        # ── B0: safety baseline ──
        if "baseline_safe" in scenario_name:
            if not ep.success and ep.parts_placed < ep.parts_total:
                failures.append("B0: task did not complete")
            if ep.d_stop_caused > 0:
                failures.append(f"B0: {ep.d_stop_caused} G1-attributed STOP(s)")
            if ep.d_slow_caused > 0:
                failures.append(f"B0: {ep.d_slow_caused} G1-attributed SLOW(s)")
            if ep.d_replan_caused > 0:
                failures.append(f"B0: {ep.d_replan_caused} G1-attributed replan(s)")
            if ep.g1_fell:
                failures.append("B0: G1 fell")

        # ── B1: static occupancy ──
        elif "static_occupancy" in scenario_name:
            has_intervention = ep.d_stop_caused > 0 or ep.d_slow_caused > 0
            if not has_intervention:
                failures.append("B1: no virtual-hand-attributed STOP or SLOW_DOWN detected")
            replan_expected = cfg.get("safety", {}).get("enable_replan", False)
            if replan_expected and ep.d_replan_caused == 0:
                failures.append("B1: replan expected but none attributed")
            if ep.parts_placed == 0:
                failures.append("B1: no parts placed (no task progress)")
            if not ep.progress_after_retreat:
                failures.append("B1: no task progress after retreat (possible deadlock)")
            if ep.g1_fell:
                failures.append("B1: G1 fell")

        # ── B2: dynamic lateral sweep (active) ──
        elif "dynamic_lateral_sweep" in scenario_name and "shadow" not in scenario_name:
            if not ep.success:
                failures.append("B2: task did not complete")
            if ep.pre_hard_stop_replan_count < 1:
                failures.append("B2: no pre-hard-stop proactive replan (ttc/ttc_forecast)")
            if ep.b2_proactive_trigger_count < 1:
                failures.append("B2: no B2 proactive trigger counted")
            if ep.held_critical_replan_count > 0:
                failures.append(
                    f"B2: held_critical replan counted ({ep.held_critical_replan_count})"
                )
            if not ep.progress_after_retreat:
                failures.append("B2: no task progress after retreat")
            if ep.retreat_attempt_count < 1:
                failures.append("B2: no retreat attempts recorded")
            if ep.recovered_attempt_count < 1 and ep.success:
                failures.append("B2: retreat without recovered/terminal pairing")
            if not ep.recovery_pairing_ok:
                failures.append(
                    f"B2: recovery/event pairing failed ({ep.events_csv_errors or ep.recovery_pairing_summary})"
                )
            if not ep.events_csv_valid:
                failures.append(
                    f"B2: events CSV audit failed ({ep.events_csv_errors})"
                )
            if ep.max_trigger_apply_latency < 0 and ep.b2_proactive_trigger_count > 0:
                failures.append("B2: could not verify trigger→apply latency")
            if ep.d_knock_off > 0:
                failures.append(f"B2: knock-off count {ep.d_knock_off}")
            if ep.g1_fell:
                failures.append("B2: G1 fell")
            _proxy_pc = getattr(ep, "proxy_physical_contact_count", 0)
            if _proxy_pc != 0:
                failures.append(f"B2: proxy_physical_contact_count={_proxy_pc}")

        # ── B4-Dynamic: shadow pairing unit ──
        elif "dynamic_lateral_sweep" in scenario_name and "shadow" in scenario_name:
            from episode_audit import audit_b4_shadow_episode

            b4_errs = audit_b4_shadow_episode(ep.__dict__)
            failures.extend(f"B4-Dynamic: {e}" for e in b4_errs)
            if not ep.events_csv_valid:
                failures.append(
                    f"B4-Dynamic: events CSV audit failed ({ep.events_csv_errors})"
                )

        # ── Unknown scenario: NOT_EVALUATED ──
        else:
            ep.scenario_pass = None
            ep.scenario_failure_reasons = "NOT_EVALUATED: unknown scenario"
            return

        ep.scenario_pass = len(failures) == 0
        ep.scenario_failure_reasons = "; ".join(failures)

    def _build_comparison_table(self) -> list[dict]:
        """Aggregate results by config name."""
        groups: dict[str, list[EpisodeResult]] = {}
        for r in self._results:
            groups.setdefault(r.config_name, []).append(r)

        rows = []
        for name, runs in groups.items():
            n = len(runs)
            rows.append({
                "config": name,
                "n_runs": n,
                "scenario_pass": all(r.scenario_pass for r in runs) if all(r.scenario_pass is not None for r in runs) else None,
                "success": f"{sum(1 for r in runs if r.success)}/{n}",
                "knock_off_rate": sum(r.d_knock_off for r in runs) / max(sum(r.parts_total for r in runs), 1),
                "intervention_rate": (
                    sum(r.tier0_stop_count + r.slowdown_count for r in runs)
                    / max(sum(r.total_steps for r in runs), 1)
                ),
                "attributed_stop_attempts": sum(r.attributed_stop_attempts for r in runs),
                "attributed_slow_attempts": sum(r.attributed_slow_attempts for r in runs),
                "attributed_replan_attempts": sum(r.attributed_replan_attempts for r in runs),
                "stop": sum(r.tier0_stop_count for r in runs) // n,
                "slow": sum(r.slowdown_count for r in runs) // n,
                "replan": sum(r.replan_count for r in runs) // n,
                "min_dist": min((r.min_surface_distance_m for r in runs if r.min_surface_distance_m != float("inf")), default=float("inf")),
                "livelock": any(r.is_livelock for r in runs),
                "parts_placed": sum(r.parts_placed for r in runs) // n,
                "parts_total": runs[0].parts_total,
            })
        return rows


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="GMDisturb Batch Test Runner")
    p.add_argument(
        "config_dir",
        help="YAML scenario config file or directory with *.yaml configs",
    )
    p.add_argument("--output-dir", default=_DEFAULT_RESULTS_DIR,
                   help="Output directory (default: results/paper_demo/ under project root)")
    p.add_argument("--timeout", type=int, default=3600,
                   help="Per-episode timeout in seconds (default: 3600)")
    args = p.parse_args()

    runner = BatchTestRunner(args.config_dir, output_dir=args.output_dir)
    summary = runner.run_all(timeout_s=args.timeout)
    print(runner.generate_comparison_report())
    print(f"\nSummary: {runner.save_batch_summary()}")
