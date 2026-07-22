# V1-C0 Semantic Supervisor Isaac 在线 shadow 接线（2026-07-22）

## 结论

Semantic advisory 已接入实时安全循环并完成 **shadow 控制隔离验证**；**尚未产生实际控制作用**。

| 项 | 值 |
|---|---|
| live_control_connected | **false** |
| intentional_control_effect | **false** |
| offline_tested | **true**（30/30 unit scripts） |
| image | `gmdisturb:semantic-shadow-v1c0-20260722` |
| image_id | `sha256:e516c78ecc3c8e365763158f1b01ec6effba9aac1290ae0e1f4d1539c2ccf1da` |
| config SHA-256 | `5bb418e2d827559ad7706f611f390c880afeae10556078ed8feef6da24ec9024` |
| real_post_count | **0** |
| isaac_formal_shadow | **false**（仅 1-step smoke，supervisor OFF） |
| paper_five_stage_complete | **false** |

---

## 接线语义

```
evaluated_semantic_gate = supervisor.evaluate(...)   # 仅日志
effective_control_gate  = existing_geometry_gate     # 唯一生效
```

- 每 `request_id` 只消费一次
- 使用 **decision-time** 几何 gate（非捕获帧旧 gate）
- 记录 source/decision step 与 `result_age_s`
- 与 `--enable_vlm` / `--enable_replan` / grasp supervisor 互斥
- 要求 `--enable_five_stage_shadow` + `--enable_safety`

---

## 隔离计数

semantic 五项 leakage = 0；原五阶段 leakage = 0；off/on control hash mismatch = 0。

---

## 下一步 V1-C1（本轮未执行）

正式短 shadow 需另批批准。预计：

- 镜像：`gmdisturb:semantic-shadow-v1c0-20260722`
- POST 上限：≤6（同 V0-C3：2× VLM+ground+track）
- 预计耗时：~1–2 min（120 steps + drain）
- CLI 骨架见 status JSON `v1c1_command_draft`
