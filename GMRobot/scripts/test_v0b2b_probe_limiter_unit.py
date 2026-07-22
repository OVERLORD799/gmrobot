#!/usr/bin/env python3
"""Offline unit tests for V0-B2B probe limiter / dry-run / no-retry rules."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import probe_v0b2b_legacy_endpoint as probe  # noqa: E402


def _tiny_png(path: Path) -> str:
    # 1x1 PNG
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )
    path.write_bytes(data)
    return probe.sha256_file(path)


class TestLedgerBudget(unittest.TestCase):
    def test_refuse_existing_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "request_ledger.jsonl"
            p.write_text("{}\n")
            with self.assertRaises(probe.ProbeError):
                probe.Ledger.reject_if_exists(p)

    def test_single_endpoint_cannot_post_twice(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = probe.Ledger.create_fresh(Path(td) / "request_ledger.jsonl")
            ledger.plan(endpoint_alias="vlm_analyze", request_id="r1", frame_id="f1", image_sha256="a")
            with self.assertRaises(probe.ProbeBudgetError):
                ledger.plan(endpoint_alias="vlm_analyze", request_id="r2", frame_id="f2", image_sha256="b")

    def test_total_posts_cannot_exceed_four(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = probe.Ledger.create_fresh(Path(td) / "request_ledger.jsonl")
            for alias in probe.ENDPOINT_ALIASES:
                ledger.plan(endpoint_alias=alias, request_id=alias, frame_id="f", image_sha256="x")
            self.assertEqual(ledger.post_count, 4)
            with self.assertRaises(probe.ProbeBudgetError):
                # unknown alias also blocked by count if we force
                ledger._aliases_used.clear()  # simulate misuse
                ledger.plan(endpoint_alias="vlm_analyze", request_id="x", frame_id="f", image_sha256="x")

    def test_timeout_finalize_consumes_budget_no_retry_slot(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = probe.Ledger.create_fresh(Path(td) / "request_ledger.jsonl")
            idx = ledger.plan(endpoint_alias="vlm_analyze", request_id="r", frame_id="f", image_sha256="h")
            ledger.finalize(request_index=idx, status="timeout", http_status=0, elapsed_s=1.0, error="timeout")
            self.assertEqual(ledger.post_count, 1)
            with self.assertRaises(probe.ProbeBudgetError):
                ledger.plan(endpoint_alias="vlm_analyze", request_id="r2", frame_id="f2", image_sha256="h")

    def test_plan_fsync_writes_planned_then_completed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "request_ledger.jsonl"
            ledger = probe.Ledger.create_fresh(path)
            idx = ledger.plan(endpoint_alias="ground", request_id="r", frame_id="f", image_sha256="h")
            ledger.finalize(request_index=idx, status="completed", http_status=200, elapsed_s=0.1)
            lines = path.read_text().strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["status"], "planned")
            self.assertEqual(json.loads(lines[1])["status"], "completed")


class TestDryRunAndGuards(unittest.TestCase):
    def _prep_paths(self, td: Path):
        scene = td / "scene"
        scene.mkdir()
        vlm = scene / "frame_000000_env0.png"
        track = scene / "frame_000010_env0.png"
        sha0 = _tiny_png(vlm)
        sha1 = _tiny_png(track)
        # make distinct
        track.write_bytes(track.read_bytes() + b"\x00")
        sha1 = probe.sha256_file(track)
        man = td / "artifacts.jsonl"
        man.write_text(
            json.dumps({"image_path": "scene/frame_000000_env0.png", "sha256": sha0})
            + "\n"
            + json.dumps({"image_path": "scene/frame_000010_env0.png", "sha256": sha1})
            + "\n"
        )
        out = td / "out"
        return vlm, track, man, out, sha0, sha1

    def test_default_dry_run_no_post(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            vlm, track, man, out, _, _ = self._prep_paths(td)
            posts = []

            def fake_post(url, payload, timeout):
                posts.append(url)
                return 200, {}, 0.01, None

            ctx = probe.ProbeContext(
                output_dir=out,
                execute=False,
                vlm_base="http://127.0.0.1:18080",
                perception_base="http://127.0.0.1:18082",
                vlm_image=vlm,
                track_image=track,
                vlm_sha=probe.sha256_file(vlm),
                track_sha=probe.sha256_file(track),
                http_post=fake_post,
            )
            rc = probe.run_probe(ctx)
            self.assertEqual(rc, 0)
            self.assertEqual(posts, [])
            self.assertFalse((out / "request_ledger.jsonl").exists())
            self.assertEqual(ctx.verdict, "DRY_RUN")

    def test_missing_execute_via_main_no_post(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            vlm, track, man, out, _, _ = self._prep_paths(td)
            with mock.patch.object(probe, "default_http_post") as m:
                rc = probe.main(
                    [
                        "--vlm-image",
                        str(vlm),
                        "--track-image",
                        str(track),
                        "--artifact-manifest",
                        str(man),
                        "--output-dir",
                        str(out),
                    ]
                )
                self.assertEqual(rc, 0)
                m.assert_not_called()

    def test_existing_ledger_rejects_execute(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            vlm, track, man, out, sha0, sha1 = self._prep_paths(td)
            out.mkdir()
            (out / "request_ledger.jsonl").write_text("{}\n")
            ctx = probe.ProbeContext(
                output_dir=out,
                execute=True,
                vlm_base="http://127.0.0.1:18080",
                perception_base="http://127.0.0.1:18082",
                vlm_image=vlm,
                track_image=track,
                vlm_sha=sha0,
                track_sha=sha1,
                http_post=lambda *a, **k: (200, {}, 0.0, None),
            )
            with self.assertRaises(probe.ProbeError):
                probe.run_probe(ctx)

    def test_vlm_fail_skips_subsequent_posts(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            vlm, track, man, out, sha0, sha1 = self._prep_paths(td)
            calls = []

            def fake_post(url, payload, timeout):
                calls.append(url)
                # return 200 JSON without extractable target schema
                return 200, {"text": "not json", "vlm_risk_type": "static"}, 0.05, None

            ctx = probe.ProbeContext(
                output_dir=out,
                execute=True,
                vlm_base="http://127.0.0.1:18080",
                perception_base="http://127.0.0.1:18082",
                vlm_image=vlm,
                track_image=track,
                vlm_sha=sha0,
                track_sha=sha1,
                http_post=fake_post,
            )
            rc = probe.run_probe(ctx)
            self.assertEqual(len(calls), 1)
            self.assertIn("/analyze", calls[0])
            self.assertEqual(ctx.verdict, "VLM_CAPABILITY_FAIL")
            self.assertEqual(rc, 1)

    def test_timeout_no_retry(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            vlm, track, man, out, sha0, sha1 = self._prep_paths(td)
            calls = []

            def fake_post(url, payload, timeout):
                calls.append(url)
                return 0, None, 1.0, "timeout"

            ctx = probe.ProbeContext(
                output_dir=out,
                execute=True,
                vlm_base="http://127.0.0.1:18080",
                perception_base="http://127.0.0.1:18082",
                vlm_image=vlm,
                track_image=track,
                vlm_sha=sha0,
                track_sha=sha1,
                http_post=fake_post,
            )
            probe.run_probe(ctx)
            self.assertEqual(len(calls), 1)
            self.assertEqual(ctx.verdict, "VLM_CAPABILITY_FAIL")
            ledger_lines = (out / "request_ledger.jsonl").read_text().strip().splitlines()
            statuses = [json.loads(x)["status"] for x in ledger_lines]
            self.assertIn("planned", statuses)
            self.assertIn("timeout", statuses)

    def test_base64_not_written_to_summaries(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            vlm, track, man, out, sha0, sha1 = self._prep_paths(td)
            good = {
                "scene_summary": "s",
                "keywords": ["robot"],
                "risk_type": "none",
                "risk_confidence": 0.1,
                "affected_entities": ["robot"],
                "predicted_consequence": "none",
                "prediction_horizon_s": 1.0,
                "explanation": "e",
                "suggested_action": "continue",
                "spatial_hint": "none",
            }

            def fake_post(url, payload, timeout):
                # ensure payload has b64 but files must not
                self.assertIn("image_b64", payload)
                if url.endswith("/analyze"):
                    return 200, {"text": json.dumps(good), "model_id": "m"}, 0.01, None
                if url.endswith("/ground"):
                    return 200, {
                        "gdino_model_id": "IDEA-Research/grounding-dino-base",
                        "sam2_checkpoint": "sam2.1_hiera_small.pt",
                        "latency_ms": 1.0,
                        "detections": [],
                    }, 0.01, None
                raise AssertionError(f"unexpected url {url}")

            ctx = probe.ProbeContext(
                output_dir=out,
                execute=True,
                vlm_base="http://127.0.0.1:18080",
                perception_base="http://127.0.0.1:18082",
                vlm_image=vlm,
                track_image=track,
                vlm_sha=sha0,
                track_sha=sha1,
                http_post=fake_post,
            )
            probe.run_probe(ctx)
            self.assertEqual(ctx.verdict, "GROUND_VALID_EMPTY")
            for name in ("vlm_request_summary.json", "ground_request_summary.json", "probe_summary.json"):
                text = (out / name).read_text()
                self.assertNotRegex(text, r"[A-Za-z0-9+/]{80,}={0,2}")  # long b64-ish
                self.assertTrue("<redacted>" in text or "image_b64" not in text or '"image_b64": "<redacted>"' in text)


class TestRedact(unittest.TestCase):
    def test_redact_strips_image_b64(self):
        obj = {"image_b64": "AAAA", "meta": {"image_b64": "BBBB", "ok": 1}}
        out = probe.redact_for_log(obj)
        self.assertEqual(out["image_b64"], "<redacted>")
        self.assertEqual(out["meta"]["image_b64"], "<redacted>")
        self.assertEqual(out["meta"]["ok"], 1)


if __name__ == "__main__":
    unittest.main()
