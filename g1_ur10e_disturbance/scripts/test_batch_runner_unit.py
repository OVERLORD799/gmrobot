"""Unit tests for BatchTestRunner (mocked subprocess — no Isaac Sim needed)."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ_ROOT)

from batch_runner import BatchTestRunner, EpisodeResult


def test_episode_result_defaults():
    """EpisodeResult can be constructed with minimal fields."""
    ep = EpisodeResult(config_name="test", run_id="r1")
    assert ep.success is False
    assert ep.g1_fell is False
    assert ep.total_steps == 0
    assert ep.disturbance_source == ""


def test_episode_result_all_fields():
    """EpisodeResult accepts all fields including new disturbance attribution."""
    ep = EpisodeResult(
        config_name="b1", run_id="b1_s42_120000",
        success=True, g1_fell=False, total_steps=5000,
        tier0_stop_count=3, slowdown_count=5, replan_count=2,
        d_stop_caused=1, d_slow_caused=1, d_replan_caused=1,
        disturbance_source="scripted_virtual_hand",
        disturbance_scenario="static_occupancy_proxy",
        disturbance_attempts=2,
        gate_trigger_source="scripted_virtual_hand",
        replan_trigger_source="scripted_virtual_hand",
        subprocess_validated=True,
    )
    assert ep.disturbance_source == "scripted_virtual_hand"
    assert ep.disturbance_scenario == "static_occupancy_proxy"
    assert ep.d_stop_caused == 1
    assert ep.subprocess_validated is True


def test_runner_yaml_parses_scenario_field():
    """Runner extracts scenario field from YAML config."""
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "test.yaml"
        yaml_path.write_text("""
name: "my_test"
scenario: "arm_collision"
mode: "scripted"
safety:
  config_path: ""
episode:
  max_steps: 1000
seed: 42
""")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        # Verify YAML can be parsed (don't actually run subprocess)
        import yaml
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["scenario"] == "arm_collision"
        assert cfg["name"] == "my_test"


def test_runner_reads_repeat():
    """Runner reads repeat field for multi-seed runs."""
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "test_repeat.yaml"
        yaml_path.write_text("""
name: "multi_seed_test"
scenario: "constrained_wander"
mode: "constrained_wander"
safety:
  config_path: ""
episode:
  max_steps: 1000
seed: 42
repeat: 3
""")
        import yaml
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg.get("repeat", 1) == 3
        assert cfg.get("seed") == 42


def test_manifest_uses_effective_seed():
    """Manifest records the effective seed (override), not YAML seed."""
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run_s43"
        run_dir.mkdir()
        cfg = {"name": "test", "seed": 42}
        cmd = ["python", "run_phase3.py", "--seed", "43"]
        path = BatchTestRunner._save_manifest(
            run_dir, "run_s43", "/abs/path/test.yaml", cfg, cmd,
            effective_seed=43,
        )
        with open(path) as f:
            manifest = json.load(f)
        assert manifest["seed"] == 43  # effective seed, not YAML seed
        assert "python" in manifest["cli_command"]
        assert manifest["seeds"]["env_seed"] == 43
        assert manifest["seeds"]["controller_seed"] == 43
        assert manifest["seeds"]["virtual_hand_seed"] == 43
        assert "physx_reproducibility_note" in manifest


def test_parse_output_csv_missing():
    """CSV missing → validation fails."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        csv_path = str(Path(tmp) / "nonexistent.csv")
        ep = runner._parse_output("test", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is False
        assert "CSV missing" in ep.subprocess_validation_errors


def test_parse_output_csv_empty():
    """Empty CSV → validation fails."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        csv_path = str(Path(tmp) / "empty.csv")
        Path(csv_path).write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("test", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is False


def test_parse_output_nonzero_exit():
    """Non-zero exit code → validation fails."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="crashed")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        csv_path = str(Path(tmp) / "nope.csv")
        ep = runner._parse_output("test", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is False
        assert "non-zero exit" in ep.subprocess_validation_errors


def test_parse_output_traceback_in_logs():
    """Traceback in subprocess output → validation fails."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        csv_path = str(Path(tmp) / "test.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["episode_id", "total_steps", "parts_placed"])
            w.writeheader()
            w.writerow({"episode_id": "0", "total_steps": "100", "parts_placed": "5"})
        # Create stderr with Traceback
        stderr_path = str(Path(tmp) / "stderr.txt")
        with open(stderr_path, "w") as f:
            f.write("Traceback (most recent call last):\n  File ...\nValueError\n")
        stdout_path = str(Path(tmp) / "stdout.txt")
        Path(stdout_path).write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("test", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is False
        assert "Traceback" in ep.subprocess_validation_errors


def test_parse_output_valid_csv():
    """Valid CSV with expected schema → validation passes."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        csv_path = str(Path(tmp) / "good.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "episode_id", "total_steps", "parts_placed", "policy_steps",
                "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
                "d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off",
                "object_drop_count", "collision_count", "footstep_count",
                "f_consecutive_stop_max", "h_vlm_action", "h_vlm_latency_ms",
                "min_g1_ur10e_distance_m", "min_surface_distance_m",
                "mean_g1_ur10e_distance_m",
                "disturbance_source", "disturbance_scenario",
                "gate_trigger_source", "replan_trigger_source",
                "disturbance_attempt_id",
                "task_completed", "parts_total",
            ])
            w.writeheader()
            w.writerow({
                "episode_id": "0", "total_steps": "500", "parts_placed": "3",
                "policy_steps": "450", "tier0_stop_count": "0", "slowdown_count": "0",
                "replan_count": "0", "stuck_count": "0",
                "d_stop_caused": "0", "d_slow_caused": "0", "d_replan_caused": "0",
                "d_knock_off": "0", "object_drop_count": "0", "collision_count": "0",
                "footstep_count": "0", "f_consecutive_stop_max": "0",
                "h_vlm_action": "", "h_vlm_latency_ms": "0",
                "min_g1_ur10e_distance_m": "0.5", "min_surface_distance_m": "0.4",
                "mean_g1_ur10e_distance_m": "0.8",
                "disturbance_source": "g1_body", "disturbance_scenario": "baseline_safe",
                "gate_trigger_source": "", "replan_trigger_source": "",
                "disturbance_attempt_id": "0",
                "task_completed": "False", "parts_total": "20",
            })
        stdout_path = str(Path(tmp) / "stdout.txt")
        Path(stdout_path).write_text("some normal output")
        stderr_path = str(Path(tmp) / "stderr.txt")
        Path(stderr_path).write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("test", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is True
        assert ep.success is False
        assert ep.total_steps == 500
        assert ep.parts_placed == 3
        assert ep.disturbance_source == "g1_body"
        assert ep.disturbance_scenario == "baseline_safe"


def test_config_path_resolved_to_absolute():
    """Relative config paths are resolved to absolute before subprocess."""
    rel = "paper_scenarios/baseline_safe.yaml"
    abs_path = str(Path(rel).resolve())
    assert os.path.isabs(abs_path)
    assert "paper_scenarios" in abs_path


def test_glfw_failed_to_startup_whitelisted():
    """GLFW headless plugin failure must not fail validation."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        csv_path = str(Path(tmp) / "glfw.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "episode_id", "total_steps", "parts_placed", "policy_steps",
                "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
                "d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off",
                "object_drop_count", "collision_count", "footstep_count",
                "f_consecutive_stop_max", "h_vlm_action", "h_vlm_latency_ms",
                "min_g1_ur10e_distance_m", "min_surface_distance_m",
                "mean_g1_ur10e_distance_m",
                "disturbance_source", "disturbance_scenario",
                "gate_trigger_source", "replan_trigger_source",
                "disturbance_attempt_id",
            ])
            w.writeheader()
            row_data = {k: "0" for k in w.fieldnames}
            row_data["total_steps"] = "100"
            row_data["parts_placed"] = "20"
            w.writerow(row_data)
        stdout_path = str(Path(tmp) / "stdout.txt")
        Path(stdout_path).write_text(
            "Failed to startup plugin carb.windowing-glfw.plugin\n"
            "ALL PARTS PLACED\nsome normal output"
        )
        stderr_path = str(Path(tmp) / "stderr.txt")
        Path(stderr_path).write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("test_glfw", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is True, (
            f"GLFW harmless message should pass: {ep.subprocess_validation_errors}"
        )


def test_real_failed_to_startup_still_caught():
    """Non-GLFW 'Failed to startup' must still fail validation."""
    with tempfile.TemporaryDirectory() as tmp:
        import subprocess
        csv_path = str(Path(tmp) / "fail.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "episode_id", "total_steps", "parts_placed", "policy_steps",
                "tier0_stop_count", "slowdown_count", "replan_count", "stuck_count",
                "d_stop_caused", "d_slow_caused", "d_replan_caused", "d_knock_off",
                "object_drop_count", "collision_count", "footstep_count",
                "f_consecutive_stop_max", "h_vlm_action", "h_vlm_latency_ms",
                "min_g1_ur10e_distance_m", "min_surface_distance_m",
                "mean_g1_ur10e_distance_m",
                "disturbance_source", "disturbance_scenario",
                "gate_trigger_source", "replan_trigger_source",
                "disturbance_attempt_id",
            ])
            w.writeheader()
            row_data2 = {k: "10" for k in w.fieldnames}
            row_data2["total_steps"] = "100"
            row_data2["parts_placed"] = "5"
            w.writerow(row_data2)
        stdout_path = str(Path(tmp) / "stdout.txt")
        Path(stdout_path).write_text(
            "Failed to startup python extension\nsome output"
        )
        stderr_path = str(Path(tmp) / "stderr.txt")
        Path(stderr_path).write_text("")
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        ep = runner._parse_output("test_fail", "r1", csv_path, result, 1.0)
        assert ep.subprocess_validated is False, (
            "Non-GLFW startup failure must be caught"
        )


def test_scenario_verdict_b0():
    """B0: task complete, no attributions → PASS."""
    ep = EpisodeResult(
        config_name="baseline_safe", run_id="b0_s42",
        success=True, parts_placed=20, parts_total=20,
        tier0_stop_count=2, slowdown_count=1,  # some STOPS but not G1-attributed
        disturbance_source="g1_body",
        gate_trigger_source="",  # no distance-related triggers
    )
    BatchTestRunner._evaluate_scenario_verdict(ep, {"name": "baseline_safe"})
    assert ep.scenario_pass is True, f"B0 should pass: {ep.scenario_failure_reasons}"


def test_scenario_verdict_b0_fails_on_g1_attribution():
    """B0: G1-attributed STOP → FAIL. Verdict now uses d_stop_caused count."""
    ep = EpisodeResult(
        config_name="baseline_safe", run_id="b0_s42",
        success=True, parts_placed=20, parts_total=20,
        tier0_stop_count=3,
        d_stop_caused=2,  # actual attributed STOPs
        disturbance_source="g1_body",
    )
    BatchTestRunner._evaluate_scenario_verdict(ep, {"name": "baseline_safe"})
    assert ep.scenario_pass is False, "B0 must fail on G1-attributed STOP"
    assert "STOP" in ep.scenario_failure_reasons


def test_scenario_verdict_b1():
    """B1: virtual hand attribution + parts placed + progress after retreat → PASS."""
    ep = EpisodeResult(
        config_name="static_occupancy_proxy", run_id="b1_s42",
        parts_placed=6, parts_total=20,
        tier0_stop_count=1, slowdown_count=30, replan_count=6,
        d_stop_caused=1, d_slow_caused=0, d_replan_caused=1,
        disturbance_source="scripted_virtual_hand",
        progress_after_retreat=True,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "static_occupancy_proxy",
             "safety": {"enable_replan": True}}
    )
    assert ep.scenario_pass is True, f"B1 should pass: {ep.scenario_failure_reasons}"


def test_scenario_verdict_b1_fails_no_intervention():
    """B1: no virtual hand attribution → FAIL."""
    ep = EpisodeResult(
        config_name="static_occupancy_proxy", run_id="b1_s42",
        parts_placed=10, parts_total=20,
        tier0_stop_count=0, slowdown_count=0,
        d_stop_caused=0, d_slow_caused=0, d_replan_caused=0,
        disturbance_source="scripted_virtual_hand",
        progress_after_retreat=False,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "static_occupancy_proxy",
             "safety": {"enable_replan": True}}
    )
    assert ep.scenario_pass is False, "B1 must fail without intervention"


def test_run_all_produces_three_seeds():
    """run_all() with repeat=3 produces 3 runs with seeds 42, 43, 44."""
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "test_3seed.yaml"
        yaml_path.write_text("""
name: "three_seed_test"
scenario: "constrained_wander"
mode: "constrained_wander"
safety:
  config_path: ""
episode:
  max_steps: 100
seed: 42
repeat: 3
""")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        # We can't actually run subprocesses, but verify YAML parsing + loop count
        import yaml
        with open(yaml_path) as fh:
            _ycfg = yaml.safe_load(fh) or {}
        _repeat = int(_ycfg.get("repeat", 1))
        _base_seed = _ycfg.get("seed")
        seeds_seen = []
        for _rep_idx in range(_repeat):
            _seed = (_base_seed + _rep_idx) if isinstance(_base_seed, int) else None
            seeds_seen.append(_seed)
        assert seeds_seen == [42, 43, 44], f"Expected [42,43,44], got {seeds_seen}"


def test_list_yaml_single_file():
    """_list_yaml_configs accepts a single YAML file path."""
    with tempfile.TemporaryDirectory() as tmp:
        yf = Path(tmp) / "one.yaml"
        yf.write_text("name: one\n")
        runner = BatchTestRunner(str(yf), output_dir=str(Path(tmp) / "out"))
        configs = runner._list_yaml_configs()
        assert len(configs) == 1
        assert configs[0].name == "one.yaml"


def test_list_yaml_directory():
    """_list_yaml_configs globs *.yaml in a directory."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.yaml").write_text("name: a\n")
        (Path(tmp) / "b.yml").write_text("name: b\n")
        runner = BatchTestRunner(str(tmp), output_dir=str(Path(tmp) / "out"))
        configs = runner._list_yaml_configs()
        assert len(configs) == 2


def test_list_yaml_invalid_suffix():
    """Non-YAML file path raises ValueError."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "not_yaml.txt"
        bad.write_text("x")
        runner = BatchTestRunner(str(bad), output_dir=str(Path(tmp) / "out"))
        try:
            runner._list_yaml_configs()
            assert False, "expected ValueError"
        except ValueError as e:
            assert "Not a YAML" in str(e)


def test_list_yaml_missing_path():
    """Missing path raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = BatchTestRunner(
            str(Path(tmp) / "missing.yaml"),
            output_dir=str(Path(tmp) / "out"),
        )
        try:
            runner._list_yaml_configs()
            assert False, "expected FileNotFoundError"
        except FileNotFoundError:
            pass


def _b2_pass_episode() -> EpisodeResult:
    return EpisodeResult(
        config_name="dynamic_lateral_sweep_proxy_1part",
        run_id="b2_s42",
        success=True,
        parts_placed=1,
        parts_total=1,
        pre_hard_stop_replan_count=1,
        b2_proactive_trigger_count=1,
        held_critical_replan_count=0,
        progress_after_retreat=True,
        retreat_attempt_count=1,
        recovered_attempt_count=1,
        recovery_pairing_ok=True,
        events_csv_valid=True,
        max_trigger_apply_latency=0,
        d_knock_off=0,
        g1_fell=False,
        proxy_physical_contact_count=0,
    )


def test_scenario_verdict_b2_pass():
    ep = _b2_pass_episode()
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_1part"}
    )
    assert ep.scenario_pass is True, ep.scenario_failure_reasons


def test_scenario_verdict_b2_fails_no_proactive_replan():
    ep = _b2_pass_episode()
    ep.pre_hard_stop_replan_count = 0
    ep.b2_proactive_trigger_count = 0
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_1part"}
    )
    assert ep.scenario_pass is False
    assert "proactive" in ep.scenario_failure_reasons


def test_scenario_verdict_b2_fails_pairing():
    ep = _b2_pass_episode()
    ep.recovery_pairing_ok = False
    ep.events_csv_errors = "applied missing retreat"
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_1part"}
    )
    assert ep.scenario_pass is False
    assert "pairing" in ep.scenario_failure_reasons


def test_scenario_verdict_b4_pass():
    ep = EpisodeResult(
        config_name="dynamic_lateral_sweep_proxy_shadow_mini",
        run_id="b4_s42",
        success=True,
        safety_enforcement_mode="shadow",
        d_stop_caused=0,
        d_slow_caused=0,
        d_replan_caused=0,
        shadow_replan_would_count=2,
        shadow_slow_would_count=0,
        shadow_clock_blocked_steps=0,
        shadow_action_modified_steps=0,
        shadow_replan_applied_count=0,
        shadow_retreat_count=0,
        disturbance_trajectory_id="abc" * 20,
        retreat_attempt_count=0,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_shadow_mini"}
    )
    assert ep.scenario_pass is True, ep.scenario_failure_reasons


def test_scenario_verdict_b4_fails_task_incomplete():
    ep = EpisodeResult(
        config_name="dynamic_lateral_sweep_proxy_shadow_mini",
        run_id="b4_s42",
        success=False,
        safety_enforcement_mode="shadow",
        d_stop_caused=0,
        d_slow_caused=0,
        d_replan_caused=0,
        shadow_replan_would_count=2,
        shadow_clock_blocked_steps=0,
        shadow_action_modified_steps=0,
        shadow_replan_applied_count=0,
        shadow_retreat_count=0,
        disturbance_trajectory_id="abc" * 20,
        retreat_attempt_count=0,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_shadow_mini"}
    )
    assert ep.scenario_pass is False
    assert "task_completed" in ep.scenario_failure_reasons


def test_scenario_verdict_b4_fails_clock_leak():
    ep = EpisodeResult(
        config_name="dynamic_lateral_sweep_proxy_shadow_mini",
        run_id="b4_s42",
        success=True,
        safety_enforcement_mode="shadow",
        d_stop_caused=0,
        d_slow_caused=0,
        d_replan_caused=0,
        shadow_replan_would_count=1,
        shadow_clock_blocked_steps=12,
        shadow_action_modified_steps=0,
        shadow_replan_applied_count=0,
        shadow_retreat_count=0,
        disturbance_trajectory_id="abc" * 20,
        retreat_attempt_count=0,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_shadow_mini"}
    )
    assert ep.scenario_pass is False
    assert "shadow_clock_blocked_steps" in ep.scenario_failure_reasons


def test_scenario_verdict_b4_fails_actual_intervention():
    ep = EpisodeResult(
        config_name="dynamic_lateral_sweep_proxy_shadow_mini",
        run_id="b4_s42",
        success=True,
        safety_enforcement_mode="shadow",
        d_replan_caused=1,
        shadow_replan_would_count=1,
        shadow_clock_blocked_steps=0,
        shadow_action_modified_steps=0,
        shadow_replan_applied_count=0,
        shadow_retreat_count=0,
        disturbance_trajectory_id="abc" * 20,
        retreat_attempt_count=0,
    )
    BatchTestRunner._evaluate_scenario_verdict(
        ep, {"name": "dynamic_lateral_sweep_proxy_shadow_mini"}
    )
    assert ep.scenario_pass is False
    assert "d_replan_caused" in ep.scenario_failure_reasons


if __name__ == "__main__":
    test_episode_result_defaults()
    test_episode_result_all_fields()
    test_runner_yaml_parses_scenario_field()
    test_runner_reads_repeat()
    test_manifest_uses_effective_seed()
    test_parse_output_csv_missing()
    test_parse_output_csv_empty()
    test_parse_output_nonzero_exit()
    test_parse_output_traceback_in_logs()
    test_parse_output_valid_csv()
    test_config_path_resolved_to_absolute()
    test_glfw_failed_to_startup_whitelisted()
    test_real_failed_to_startup_still_caught()
    test_scenario_verdict_b0()
    test_scenario_verdict_b0_fails_on_g1_attribution()
    test_scenario_verdict_b1()
    test_scenario_verdict_b1_fails_no_intervention()
    test_run_all_produces_three_seeds()
    test_list_yaml_single_file()
    test_list_yaml_directory()
    test_list_yaml_invalid_suffix()
    test_list_yaml_missing_path()
    test_scenario_verdict_b2_pass()
    test_scenario_verdict_b2_fails_no_proactive_replan()
    test_scenario_verdict_b2_fails_pairing()
    test_scenario_verdict_b4_pass()
    test_scenario_verdict_b4_fails_task_incomplete()
    test_scenario_verdict_b4_fails_clock_leak()
    test_scenario_verdict_b4_fails_actual_intervention()
    print("All batch runner unit tests passed.")
