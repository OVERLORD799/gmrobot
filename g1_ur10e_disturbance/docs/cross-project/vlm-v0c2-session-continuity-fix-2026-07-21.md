# V0-C2.1 Session Continuity 审计修复（2026-07-21）

## 结论

| 项 | 值 |
|---|---|
| v0c2_fail_preserved | **true**（verdict 仍为 FAIL） |
| reason (V0-C2) | **session_continuity_not_recorded** |
| session_match_computed_before_redaction | **true** |
| raw_session_logged | **false** |
| offline_tests | **108 OK**（含 session continuity 14） |
| v0c3_image | `gmdisturb:five-stage-shadow-v0c3-20260721` |
| v0c3_image_id | `sha256:cab6bf5cf637a1f16bd1ac4b14cd6611bb85c7c75ec71cacfddffc963b6ed452` |
| real_post_count | **0** |
| v0c3_shadow_not_run | **true** |

本轮未重跑 V0-C2，未 POST，未连网跑正式 shadow。

---

## V0-C2 FAIL 审计说明（不可改成 PASS）

- 实际 pipeline **2/2**；track **0→0**；`initialized→tracking`
- 仅写了 `session_present=true`；脱敏后无法严格证明远端 session 相同
- **不是**远端已证实 mismatch
- 严格失败原因：`session_continuity_not_recorded`

---

## session_match 语义

| 帧 | applicable | match | continuity_verified | session_ref |
|---|---|---|---|---|
| init | false | null | false | `session_N`（成功 init/reacquire 递增） |
| step 同 session | true | true | true | 同 ref |
| step 异 session | true | false | false | 保留旧 ref；`ok=false`；`error_type=session_id_mismatch`；不覆盖本地 session |

比较在 **写入 `<redacted>` 之前** 用内存中的 `expected_session_id` vs `response_session_id`。  
禁止用 `<redacted>==<redacted>` 或仅用 track_id 代替。

---

## 离线 / smoke

- 108 测试全过
- import + config resolve：`V0C3_IMPORT_OK`
- 1-step Isaac（shadow 关）：exit 0，camera OK，无 Traceback

先验镜像未覆盖：defe / b28c / b32f / 882da3。
