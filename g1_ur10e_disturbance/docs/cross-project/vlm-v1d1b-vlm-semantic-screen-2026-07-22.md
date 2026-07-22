# V1-D1B-S 固定 RGB 2-POST VLM-only 语义筛选（2026-07-22）

## 1. Verdict

**`SEMANTIC_SCREEN_FAIL`**

历史 capture verdict **`GEOMETRY_OVERLAP` 保留，未改写为 PASS**。本轮仅评估图像语义能力，与 geometry verdict 分开。

未启动 Isaac；未调用 `/ground`/`/track`；未改场景/图片/prompt/阈值；POST=2；retry=0；未跑正式 D1；无 active 控制。

### 门禁逐项

| # | 条件 | 结果 |
|---|---|---|
| 1 | POST 恰好 2 | **PASS** |
| 2 | 两次 HTTP 成功 | **PASS** |
| 3 | 两次 parse_ok=true | **PASS** |
| 4 | 两次 synthetic=false | **PASS** |
| 5 | risk_type ∈ {functional, dynamic} | **FAIL** — 均为 `static` |
| 6 | risk_confidence ≥ 0.85 | **FAIL** — 0.3 / 0.7 |
| 7 | recommended_action=slow_down | **PASS** |
| 8 | 规范化 semantic_key 一致 | **FAIL** — 两 key 不同 |
| 9 | artifact SHA 与 capture 一致 | **PASS**（见下） |
| 10 | 无重试 | **PASS**（retry=0） |
| 11 | 无凭据/raw session 泄漏 | **PASS** |

失败原因（不调 prompt、不降阈值、不做第三次尝试）：
1. `5_risk_type_functional_or_dynamic`
2. `6_confidence_ge_0_85`
3. `8_semantic_key_identical`

---

## 2. 输入路径 / SHA

| step | path | SHA256 |
|---|---|---|
| 100 | `results/paper_demo/v1d1b_functional_blockage_capture_20260722/scene/frame_000100_env0.png` | `3fdafcbb6cc3848309c4e2ed5a51b52f167fd34db1432c41840a0f960377fe11` |
| 200 | `results/paper_demo/v1d1b_functional_blockage_capture_20260722/scene/frame_000200_env0.png` | `40d0966ad933431a1ff01aa0d3e1a7f36720c40c63c6c54cbf221aac43ac337e` |

- step100：**与 capture manifest 一致**。
- step200：同次 capture 的 `camera_save_interval` 产物；`plan_steps=[0,100]` 未列入 manifest frames；**按同次 scene 原文件钉死 SHA**，未裁剪/放大/标注/改色/重编码/换帧。

---

## 3. VLM / prompt / schema

| 项 | 值 |
|---|---|
| gateway | `vlm_client_legacy_gateway.yaml` / `contract_mode=legacy_v2` |
| base_url | `http://127.0.0.1:18080` |
| endpoint | `/analyze` |
| prompt_version | `five_stage_safety_v1` |
| schema_version | `five_stage_vlm_v1` |
| model_id（响应） | `Qwen2.5-VL-7B-Instruct-4bit-nf4` |
| health | 1× GET `/health` → HTTP 200，`status=ok` |

---

## 4. POST 数与顺序

1. frame100 → `/analyze`
2. frame200 → `/analyze`

POST=**2**；无 `/ground`/`/track`；无第三帧；无 retry。

---

## 5. 每帧 latency

| step | latency_ms（服务端） | wall_ms |
|---|---|---|
| 100 | 4946.5 | 5253.8 |
| 200 | 5480.2 | 6146.0 |

---

## 6. risk_type / confidence / action

| step | risk_type | risk_confidence | recommended_action |
|---|---|---|---|
| 100 | `static` | 0.3 | `slow_down` |
| 200 | `static` | 0.7 | `slow_down` |

未用 legacy 字段补造缺失字段。

---

## 7. entities / keywords 摘要（脱敏）

| step | entities | keywords | explanation 摘要 |
|---|---|---|---|
| 100 | robotic arm, orange sphere | robotic arm, orange sphere, green containers, black objects | 臂靠近橙色球体，可能碰撞 |
| 200 | robotic arm, container, small objects, spherical object | 同左 | 臂靠近球形物与容器，可能碰撞 |

VLM 侧重「臂–球/物邻近」的 **static** 碰撞语义，**未**输出 functional/dynamic 占用阻塞语义。

---

## 8. semantic_key

- step100: `static|slow_down|orange sphere|robotic arm|collision|left`
- step200: `static|slow_down|container|robotic arm|small objects|spherical object|collision|right`
- **不一致**

---

## 9. 离线 supervisor

**未执行**（门禁未过；不得在 FAIL 上做 offline accepted）。

预期仅在 PASS 时：第1条 `consistency_pending`，第2条 `accepted`（offline_replay_only，非 live-loop）。

---

## 10. 对应 step100/200 geometry 证据

| step | g_rule | reason | TTC | dist_ee_human |
|---|---|---|---|---|
| 100 | 0 (ALLOW) | allow | inf | ~0.562 |
| 200 | 0 (ALLOW) | allow | inf | ~0.494 |

补充审计（不改写 GEOMETRY_OVERLAP）：
- 非 ALLOW 仅在 step **1–55** 离散区间（26 步）
- step **56–279** 全部 ALLOW
- 早期 TTC 源：静止 `human_hand` vs 运动 EE 相对接近
- **不是** part_5000 blocker 距离 margin 穿透

---

## 11. retry

**0**

---

## 12. 脱敏扫描

对 `results/.../v1d1b_vlm_semantic_screen_20260722/` 扫描：`api_key` / bearer / password / secret / session / private key → **0 hits**。  
报告仅摘要；raw 留在受控结果目录。

---

## 13. 是否值得修复 geometry 时序并进入正式 D1

**否（本轮结论）。**

理由：固定 ALLOW 帧上的 VLM 输出为 `static` + 低置信 + key 不一致，**语义门禁未过**。仅修复 geometry 时序无法把本对 RGB 变成合格 functional/dynamic 正例；进入正式 D1 的前提是语义筛选 PASS。下一步应另议场景/资产语义可识别性（仍禁止本轮调 prompt/阈值/第三次 POST）。

---

## 14. 产物

- 结果：`results/paper_demo/v1d1b_vlm_semantic_screen_20260722/`
- 状态 JSON：`docs/cross-project/vlm-v1d1b-vlm-semantic-screen-2026-07-22.json`

### git diff --stat（工作树快照）

```
 GMRobot/configs/perception_client.yaml             |   1 +
 GMRobot/configs/vlm_client.yaml                    |   3 +
 GMRobot/deploy/ai_server/vlm_service.py            | 119 +++++-----
 GMRobot/scripts/gm_state_machine_agent.py          | 249 +++++++++++++++++++++
 GMRobot/source/GMRobot/GMRobot/__init__.py         |  14 +-
 .../source/GMRobot/GMRobot/perception/__init__.py  |  20 +-
 .../source/GMRobot/GMRobot/perception/client.py    | 101 ++++++++-
 .../tasks/manager_based/gmrobot/gmrobot_env_cfg.py |   5 +
 GMRobot/source/GMRobot/GMRobot/vlm/__init__.py     |  35 ++-
 GMRobot/source/GMRobot/GMRobot/vlm/client.py       | 149 ++++++++++--
 10 files changed, 616 insertions(+), 80 deletions(-)
```

（另有大量既有 untracked 五阶段/shadow/D1A/D1B 文件；本轮 **未新增代码提交**，仅新增结果与文档。）
