# V1-D2B 固定 D1B RGB：v1 基线 vs v2 任务上下文对照（2026-07-22）

## 1. Verdict

**`D2B_TASK_CONTEXT_FAIL`**

失败门禁（未重试、未改 prompt、未降 confidence、未执行 fusion accepted）：

| # | 条件 | 结果 |
|---|---|---|
| 1 | POST=2 | PASS |
| 2 | HTTP/schema/parse | PASS |
| 3 | synthetic=false | PASS |
| 4 | native risk=`functional` | **FAIL** — 均为 `static` |
| 5 | native conf≥0.85 | **FAIL** — 均为 `0.8` |
| 6 | action=`slow_down` | PASS |
| 7 | target/phase 与 TaskContext 匹配；occupied=`unknown` | PASS |
| 8 | semantic_key_v2 一致 | **FAIL**（entity+phase 不同） |
| 9 | 无 temporal evidence | PASS |
| 10 | SHA 一致 | PASS |
| 11 | retry=0 | PASS |
| 12 | 无敏感泄漏 | PASS |

**明确结论：** 本地 fusion/工程路径可用，但 **当前 Qwen + prompt v2 仍无法提供稳定的 `functional@≥0.85` 控制级语义证据**。  
**不具备进入 D2C / 构造 active 场景的条件。** 下一步应为专门的 prompt/model 评估，而不是放宽门禁或进 Isaac 正例。

历史 **未改写**：D1B=`GEOMETRY_OVERLAP`；D1B-S=`SEMANTIC_SCREEN_FAIL`。

---

## 2. 输入 SHA

| step | path | SHA256 |
|---|---|---|
| 100 | `…/v1d1b_functional_blockage_capture_20260722/scene/frame_000100_env0.png` | `3fdafcbb6cc3848309c4e2ed5a51b52f167fd34db1432c41840a0f960377fe11` |
| 200 | `…/frame_000200_env0.png` | `40d0966ad933431a1ff01aa0d3e1a7f36720c40c63c6c54cbf221aac43ac337e` |

未裁剪/缩放/标注/重编码/换帧。

---

## 3. 版本

| 项 | 值 |
|---|---|
| model（响应） | `Qwen2.5-VL-7B-Instruct-4bit-nf4` |
| prompt_version | `five_stage_safety_v2_temporal` |
| schema_version | `five_stage_vlm_v2` |
| fusion_version | `five_stage_temporal_fusion_v1` |
| semantic_key_version | `v2` |
| temporal_fusion_enabled | true（显式） |
| temporal_context_present | **false** |
| motion_evidence_source | **none** |

---

## 4. v1 历史基线（D1B-S，**未重复 POST**）

| step | risk | conf | action | semantic_key_v1 |
|---|---|---|---|---|
| 100 | static | 0.3 | slow_down | `static\|…\|orange sphere\|…\|left` |
| 200 | static | 0.7 | slow_down | `static\|…\|container\|…\|right` |

历史 verdict：`SEMANTIC_SCREEN_FAIL`（单独批次，不与本次 v2 混称同跑）。

---

## 5–6. v2 两条结果 / POST

顺序：frame100 → `/analyze`；frame200 → `/analyze`。  
**POST=2**；retry=0；无 ground/track；无 Isaac。

| step | latency_ms（服务端） | wall_ms | native risk | conf | action |
|---|---|---|---|---|---|
| 100 | 4849.5 | 5226 | **static** | **0.8** | slow_down |
| 200 | 4585.3 | 4914 | **static** | **0.8** | slow_down |

---

## 7. Exact TaskSemanticContext

**共同：** `task_name=pick_place`，`task_goal_type=place_into_container`，`source_container=container_a`，`target_container=container_b`，`placement_target_occupied=unknown`（**禁止 true**），`context_source=scenario_protocol`。  
未写入 risk_type / action / confidence /「B 已阻塞」暗示。

| step | task_phase | held_object_class | transport_active | 依据（capture CSV，非答案） |
|---|---|---|---|---|
| 100 | approach | none | false | z≈0.135、gripper 开、无 held_part |
| 200 | transit | industrial_part | true | held_part 非空、gripper 闭、抬升中 |

---

## 8. Native risk / conf / action / 摘要

| step | entities | keywords | explanation 摘要 |
|---|---|---|---|
| 100 | robotic arm, orange sphere | … approaching | 臂靠近橙球，碰撞风险 |
| 200 | robotic_arm, containers | open_container | 臂靠近开口容器，碰撞风险 |

仍偏向 **静态邻近几何**，未输出 functional 占用语义。

---

## 9. semantic_key 对照

| | v1 key | v2 key payload |
|---|---|---|
| 100 | static + orange sphere + left | static / slow_down / sphere / container_b / **approach** / none |
| 200 | static + container + right | static / slow_down / container / container_b / **transit** / none |
| 一致性 | v1 不一致 | v2 **仍不一致**（entity + phase） |

---

## 10. 离线 fusion / supervisor

**未执行 accepted 路径**（原生门禁未过）。  
审计侧 fusion：`track_evidence=None` → static 单独拒绝（符合设计）。

---

## 11–12. Leakage / 脱敏

leakage 计数器未触发控制作用；结果树敏感扫描 **0 hits**。raw 仅存受控目录。

---

## 13. Temporal 未验证边界

- **无**真实 SAM2 temporal evidence
- **未**验证 static→dynamic temporal fusion
- **未**宣称方案 B live 验证
- **未**用 D1A/D1B 屏幕位移冒充 SAM2 速度
- temporal 真实验证 **留给未来有连续 tracking 的阶段**（当前 **不进 D2C**）

---

## 14. 是否具备进入 D2C

**否。**

---

## 15. git diff --stat（工作树快照）

```
 10 files changed, 628 insertions(+), 80 deletions(-)
```

（另有既有 untracked D2A 模块等；本轮新增结果目录与本文档；仅小改 `task_context.py` 增加枚举 `scenario_protocol`。）

### 产物

- `results/paper_demo/v1d2b_task_context_vlm_replay_20260722/`
- `docs/cross-project/vlm-v1d2b-task-context-replay-2026-07-22.md`
- `docs/cross-project/vlm-v1d2b-task-context-replay-2026-07-22.json`

**已停止。**
