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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from paths import GMDISTURB_ROOT, PHASE3_SCRIPT, ISAACLAB_ROOT, CONDA_PYTHON, GMROBOT_ROOT


# ---------------------------------------------------------------------------
# Episode result
# ---------------------------------------------------------------------------

@dataclass
class EpisodeResult:
    """Parsed metrics from a single episode run."""
    config_name: str
    run_id: str
    success: bool
    g1_fell: bool
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
    _PYTHON = CONDA_PYTHON

    def __init__(self, config_dir: str, output_dir: str = "/tmp/gmdisturb_batch"):
        self.config_dir = Path(config_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._results: list[EpisodeResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self, *, max_parallel: int = 1, timeout_s: int = 3600) -> dict:
        """Run all YAML configs in *config_dir*, return aggregated summary.

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
        yaml_files = sorted(self.config_dir.glob("*.yaml")) + sorted(
            self.config_dir.glob("*.yml")
        )
        if not yaml_files:
            raise FileNotFoundError(f"No YAML configs found in {self.config_dir}")

        print(f"[batch_runner] {len(yaml_files)} config(s) in {self.config_dir}")
        for yf in yaml_files:
            result = self.run_single(str(yf), timeout_s=timeout_s)
            self._results.append(result)

        self.save_batch_summary()
        comparison = self._build_comparison_table()
        return {
            "runs": [r.__dict__ for r in self._results],
            "comparison_table": comparison,
        }

    def run_single(self, config_path: str, *, timeout_s: int = 3600) -> EpisodeResult:
        """Run a single test configuration.

        Spawns ``run_phase3.py`` in a subprocess with the config's parameters.
        Parses the resulting CSV for metrics.

        Parameters
        ----------
        config_path:
            Path to a YAML scenario config file.
        timeout_s:
            Episode timeout in seconds.

        Returns
        -------
        :class:`EpisodeResult` for this run.
        """
        import yaml

        config_path = str(config_path)
        config_name = Path(config_path).stem

        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}

        # Build CLI args from YAML config.
        scenario = cfg.get("name", config_name)
        mode = cfg.get("mode", "constrained_wander")
        safety_cfg = cfg.get("safety", {})
        safety_path = safety_cfg.get("config_path", "")
        episode_cfg = cfg.get("episode", {})
        max_steps = episode_cfg.get("max_steps", 10000)
        enable_vlm = cfg.get("sensors", {}).get("enable_head_camera", False)
        enable_replan = safety_cfg.get("enable_replan", False)
        virtual_hand_cfg = cfg.get("virtual_hand", {})
        virtual_hand_radius = virtual_hand_cfg.get("radius", None)
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
        config_path = cfg.get("config_path")

        run_id = f"{config_name}_{time.strftime('%H%M%S')}"
        csv_path = str(self.output_dir / f"{run_id}.csv")

        cmd = [
            self._PYTHON, "-u", self._PHASE3,
            "--max-steps", str(max_steps),
            "--output_csv", csv_path,
        ]
        if headless:
            cmd.append("--headless")
        if config_path:
            cmd.extend(["--config", str(config_path)])
        if mode == "scripted" and scenario:
            cmd.extend(["--scenario", scenario])
        elif mode == "vlm_guided":
            cmd.append("--vlm")
        if safety_path:
            safety_abs = os.path.join(self._PROJ_ROOT, safety_path)
            if not os.path.exists(safety_abs):
                safety_abs = os.path.join(GMROBOT_ROOT, safety_path)
            if os.path.exists(safety_abs):
                cmd.extend(["--safety-config", safety_abs])
            else:
                print(f"[batch_runner] WARNING: safety config not found at "
                      f"{self._PROJ_ROOT}/{safety_path} or GMRobot root — "
                      f"running WITHOUT --safety-config")
        # H10 fix (2026-07-13): compute a single use_vlm boolean to avoid
        # duplicate --vlm.  Both mode=='vlm_guided' and sensors.enable_head_camera
        # enable VLM; the flag only needs to appear once.
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

        t0 = time.monotonic()
        env = os.environ.copy()
        env["CONDA_PREFIX"] = CONDA_PREFIX
        env["OMNI_KIT_ACCEPT_EULA"] = "YES"
        env["DISPLAY"] = os.environ.get("DISPLAY", ":20")

        # R6 M2 fix: use cwd= instead of shell=True.  Eliminates command
        # injection surface (YAML config values were spliced into a shell
        # command) and fixes argument splitting for paths with spaces (L4).
        try:
            result = subprocess.run(
                cmd,
                cwd=self._ISAAC_LAB,
                shell=False,
                env=env,
                capture_output=True, text=True,
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
            "| config | success | knock_off% | interv% | STOP | SLOW | "
            "REPLAN | min_dist | livelock | parts |\n"
            "|--------|---------|------------|---------|------|------|"
            "--------|----------|----------|-------|"
        )
        rows = []
        for r in table:
            rows.append(
                f"| {r['config']} | {r['success']} | {r['knock_off_rate']:.0%} | "
                f"{r['intervention_rate']:.1%} | {r['stop']} | {r['slow']} | "
                f"{r['replan']} | {r['min_dist']:.2f}m | "
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
        """Parse subprocess stdout + CSV into an EpisodeResult."""
        ep = EpisodeResult(
            config_name=config_name, run_id=run_id,
            success=False, csv_path=csv_path, elapsed_s=elapsed,
        )

        output = result.stdout + result.stderr
        if result.returncode != 0:
            ep.raw_error = result.stderr[:500] if result.stderr else f"exit={result.returncode}"
            return ep

        ep.success = "ALL PARTS PLACED" in output
        ep.g1_fell = "G1 collapsed" in output

        # Parse CSV for structured metrics.
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ep.parts_placed = int(row.get("parts_placed", 0))
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
        except Exception as e:
            ep.raw_error = f"CSV parse error: {e}"

        return ep

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
                "success": f"{sum(1 for r in runs if r.success)}/{n}",
                "knock_off_rate": sum(r.d_knock_off for r in runs) / max(sum(r.parts_total for r in runs), 1),
                "intervention_rate": (
                    sum(r.tier0_stop_count + r.slowdown_count for r in runs)
                    / max(sum(r.total_steps for r in runs), 1)
                ),
                "stop": sum(r.tier0_stop_count for r in runs) // n,
                "slow": sum(r.slowdown_count for r in runs) // n,
                "replan": sum(r.replan_count for r in runs) // n,
                "min_dist": min(r.min_distance_m for r in runs),
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
    p.add_argument("config_dir", help="Directory with YAML scenario configs")
    p.add_argument("--output-dir", default="/tmp/gmdisturb_batch",
                   help="Output directory (default: /tmp/gmdisturb_batch)")
    p.add_argument("--timeout", type=int, default=3600,
                   help="Per-episode timeout in seconds (default: 3600)")
    args = p.parse_args()

    runner = BatchTestRunner(args.config_dir, output_dir=args.output_dir)
    summary = runner.run_all(timeout_s=args.timeout)
    print(runner.generate_comparison_report())
    print(f"\nSummary: {runner.save_batch_summary()}")
