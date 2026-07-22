#!/usr/bin/env python3
"""Unit tests for V0-B2B track-step continuation limiter and track_id=0 rules."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import probe_v0b2b_track_step_continuation as cont  # noqa: E402


def _tiny_png(path: Path) -> str:
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )
    path.write_bytes(data)
    return cont.sha256_file(path)


def _parent_init(path: Path, session_id: str = "sess-secret-uuid", track_id: int = 0) -> None:
    path.write_text(
        json.dumps(
            {
                "http_status": 200,
                "response": {
                    "session_id": session_id,
                    "tracks": [{"track_id": track_id, "box_xyxy": [1, 2, 3, 4], "mask_area": 10}],
                },
            }
        )
        + "\n"
    )


class TestTrackIdZero(unittest.TestCase):
    def test_track_id_zero_is_valid(self):
        self.assertTrue(cont.is_valid_track_id(0))
        self.assertTrue(cont.track_id_equals(0, 0))

    def test_not_none_not_bool(self):
        self.assertFalse(cont.is_valid_track_id(None))
        # Must not use bool(track_id): bool(0) is False but 0 is valid
        self.assertTrue(cont.is_valid_track_id(0))
        self.assertFalse(bool(0))  # document the footgun
        self.assertFalse(cont.is_valid_track_id(False))


class TestContinuationBudget(unittest.TestCase):
    def test_max_one_post(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = cont.ContinuationLedger.create_fresh(Path(td) / "request_ledger.jsonl")
            ledger.plan(image_sha256="abc", expected_track_id=0)
            with self.assertRaises(cont.ContinuationBudgetError):
                ledger.plan(image_sha256="abc", expected_track_id=0)

    def test_ledger_exists_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "request_ledger.jsonl"
            p.write_text("{}\n")
            with self.assertRaises(cont.ContinuationError):
                cont.ContinuationLedger.reject_if_exists(p)

    def test_ledger_omits_session_and_b64(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "request_ledger.jsonl"
            ledger = cont.ContinuationLedger.create_fresh(path)
            ledger.plan(image_sha256="deadbeef", expected_track_id=0)
            ledger.finalize(request_index=1, status="timeout", http_status=0, elapsed_s=1.0, error="timeout")
            text = path.read_text()
            self.assertNotIn("session_id", text)
            self.assertNotIn("image_b64", text)
            self.assertIn("track_step_continuation", text)

    def test_timeout_no_second_plan(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = cont.ContinuationLedger.create_fresh(Path(td) / "request_ledger.jsonl")
            idx = ledger.plan(image_sha256="x", expected_track_id=0)
            ledger.finalize(request_index=idx, status="timeout", elapsed_s=1.0, error="timeout")
            with self.assertRaises(cont.ContinuationBudgetError):
                ledger.plan(image_sha256="x", expected_track_id=0)


class TestContinuationFlow(unittest.TestCase):
    def test_missing_session_zero_posts(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            parent = td / "init.json"
            parent.write_text(json.dumps({"response": {}}) + "\n")
            img = td / "frame.png"
            _tiny_png(img)
            out = td / "out"
            posts = []

            def fake_post(url, payload, timeout):
                posts.append(1)
                return 200, {}, 0.01, None

            ctx = cont.ContinuationContext(
                output_dir=out,
                execute=True,
                perception_base="http://127.0.0.1:18082",
                parent_init_path=parent,
                step_image=img,
                image_sha256=cont.sha256_file(img),
                http_post=fake_post,
            )
            rc = cont.run_continuation(ctx)
            self.assertEqual(posts, [])
            self.assertEqual(rc, 1)
            self.assertEqual(ctx.verdict, "SESSION_EXPIRED")

    def test_http_error_no_retry(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            parent = td / "init.json"
            _parent_init(parent, session_id="sess-abc")
            img = td / "frame.png"
            _tiny_png(img)
            out = td / "out"
            calls = []

            def fake_post(url, payload, timeout):
                calls.append(url)
                return 500, {"detail": "boom"}, 0.01, None

            ctx = cont.ContinuationContext(
                output_dir=out,
                execute=True,
                perception_base="http://127.0.0.1:18082",
                parent_init_path=parent,
                step_image=img,
                image_sha256=cont.sha256_file(img),
                http_post=fake_post,
            )
            cont.run_continuation(ctx)
            self.assertEqual(len(calls), 1)
            self.assertEqual(ctx.verdict, "TRACK_STEP_HTTP_FAIL")
            # cannot plan again
            ledger = cont.ContinuationLedger(path=out / "request_ledger.jsonl", _count=1)
            with self.assertRaises(cont.ContinuationBudgetError):
                ledger.plan(image_sha256="x")

    def test_success_associates_track_id_zero(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            parent = td / "init.json"
            secret = "do-not-print-this-session"
            _parent_init(parent, session_id=secret, track_id=0)
            img = td / "frame.png"
            _tiny_png(img)
            out = td / "out"

            def fake_post(url, payload, timeout):
                self.assertEqual(payload["session_id"], secret)
                self.assertEqual(payload["action"], "step")
                return 200, {
                    "session_id": secret,
                    "frame_index": 10,
                    "re_detected": False,
                    "tracks": [
                        {
                            "track_id": 0,
                            "box_xyxy": [10.0, 20.0, 30.0, 40.0],
                            "mask_area": 100,
                            "sam2_score": 0.9,
                            "velocity_xy_px_s": [1.0, 2.0],
                            "speed_px_s": 2.2,
                            "direction_deg": 45.0,
                        }
                    ],
                }, 0.05, None

            ctx = cont.ContinuationContext(
                output_dir=out,
                execute=True,
                perception_base="http://127.0.0.1:18082",
                parent_init_path=parent,
                step_image=img,
                image_sha256=cont.sha256_file(img),
                http_post=fake_post,
            )
            # capture stdout
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cont.run_continuation(ctx)
            stdout = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertEqual(ctx.verdict, "LEGACY_GATEWAY_FEASIBLE_COMPOSITE")
            self.assertNotIn(secret, stdout)
            summary = json.loads((out / "continuation_summary.json").read_text())
            self.assertTrue(summary["session_match"])
            self.assertTrue(summary["track_id_associated"])
            self.assertNotIn(secret, json.dumps(summary))
            ledger_text = (out / "request_ledger.jsonl").read_text()
            self.assertNotIn(secret, ledger_text)
            self.assertNotIn("image_b64", ledger_text)
            # response file redacts session
            resp = json.loads((out / "track_step_response.json").read_text())
            self.assertEqual(resp["response"]["session_id"], "<redacted>")

    def test_no_image_b64_in_logs(self):
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            parent = td / "init.json"
            _parent_init(parent, session_id="sess-abc")
            img = td / "frame.png"
            _tiny_png(img)
            out = td / "out"

            def fake_post(url, payload, timeout):
                return 200, {
                    "session_id": "sess-abc",
                    "frame_index": 10,
                    "tracks": [
                        {
                            "track_id": 0,
                            "box_xyxy": [1, 2, 3, 4],
                            "mask_area": 5,
                            "sam2_score": 0.5,
                        }
                    ],
                }, 0.01, None

            ctx = cont.ContinuationContext(
                output_dir=out,
                execute=True,
                perception_base="http://127.0.0.1:18082",
                parent_init_path=parent,
                step_image=img,
                image_sha256=cont.sha256_file(img),
                http_post=fake_post,
            )
            cont.run_continuation(ctx)
            for name in ("request_summary.json", "continuation_summary.json", "request_ledger.jsonl"):
                text = (out / name).read_text()
                self.assertNotRegex(text, r'"image_b64":\s*"[A-Za-z0-9+/=]{20,}"')


if __name__ == "__main__":
    unittest.main()
