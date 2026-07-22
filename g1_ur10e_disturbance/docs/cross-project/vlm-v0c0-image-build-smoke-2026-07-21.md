# V0-C0 Shadow 调度修复 + 独立镜像构建与无网络 smoke（2026-07-21）

## 结论

| 项 | 值 |
|---|---|
| scheduler_fixed | **true** |
| max_submissions_tested | **2**（200 step → 恰好 2 次 submit；第 3 interval 不提交） |
| offline_tests | **73 OK** |
| image tag | `gmdisturb:five-stage-shadow-v0c-20260721` |
| image_id | `sha256:b28c65a6b7c5547a15299fe1cf6974b7d95011fda01dc677081f5d55659b61b7` |
| created | `2026-07-21T19:39:07.580373341+08:00` |
| frozen `b4-p010-20260721` | **unchanged** `sha256:defe95e7…c820b68` |
| import_smoke | **V0C_IMPORT_OK** |
| isaac_one_step_smoke | **exit 0**；camera `scene_rgb` 就绪；无 Traceback；未启用 shadow |
| real_post_count | **0** |
| isaac_shadow_validated | **false** |
| paper_five_stage_complete | **false** |

本轮**未**执行真实 VLM/perception POST，**未**跑正式 five-stage shadow。

---

## 一、调度修复

新增 `GMRobot/shadow/scheduler.py`（`FiveStageShadowScheduler`），并接入 `gm_state_machine_agent.py`：

1. shadow **不再嵌套于** `enable_safety`；仅要求 `--enable_cameras`。
2. 每步：interval 到则 submit；**每步非阻塞 poll**；按 `(request_id, frame_id, completed_at_s)` 去重写 logger。
3. 计数：`last_logged_result_key` / `configured_max_submissions` / `submitted_count` / `logged_result_count`。
4. `max_submissions: 0` = 不限制；正数达上限后不再 submit。
5. shutdown：再 poll 一次补记未记录结果；不重复写；`stop(timeout_s=2.0)`。
6. 仍不进入 gate / action / clock / replan / protocol。

顺带修复：`five_stage_worker` 对 `perception.schema` 使用包内相对导入（兼容 Isaac 包路径与离线单测）。

---

## 二、配置

`GMRobot/configs/five_stage_shadow_legacy_gateway_v0c.yaml`

- `enabled: false`（正式由 CLI 显式开启）
- `max_submissions: 2`
- `contract_mode: legacy_v2`
- localhost endpoints only；无凭据

config sha256: `482b40d855abffd8bbcf160a7a143a005a69d600c444c828d358ed7a090fe52e`

---

## 三、离线测试

含 V0-A / B3 / B3.1 / B4.1 / scheduler / logger / schema/contract：**73 passed**。

scheduler 覆盖：无 safety 仍 submit；`interval=50,max_submissions=2`→恰好 2；poll 不重复日志；慢 worker / shutdown 补记；stale 唯一；leakage=0；canonical+legacy 回调形状。

---

## 四、镜像

```
./build.sh --tag gmdisturb:five-stage-shadow-v0c-20260721
```

| 字段 | 值 |
|---|---|
| base | `nvcr.io/nvidia/isaac-sim:5.1.0` |
| base digest | `nvcr.io/nvidia/isaac-sim@sha256:f3563cb2ba0c18af0b2fb321360dcb73a917b899f879e3213623d6bee484fa54` |
| git revision | `46a76ad8bd2ad7ad1f0051239dfeaafb96782bc5` |
| dirty worktree | dirty（约 54 项未提交 V0-A/B/C 工程变更） |
| V0-A/B3/B4 关键源码 hash | `d27abd60f0def9ad6d8919b6bd65d4a1c013fc6a485ab5dc46653dbd5e4e2578` |
| push | **no** |
| 覆盖冻结 tag | **no** |

元数据：`g1_ur10e_disturbance/docker/image_meta/five-stage-shadow-v0c-20260721.txt`

---

## 五、Import / Isaac smoke

Import（无 Kit、路径导入子模块，避免 `GMRobot/__init__` 拉起 isaaclab/pxr）：`V0C_IMPORT_OK`；镜像内含 legacy gateway、scheduler、stale unique、v0c config。

Isaac 1-step（**未** `--enable_five_stage_shadow`）：

- 日志：`results/paper_demo/v0c_image_smoke_20260721/isaac_one_step_smoke.log`
- camera group `scene_rgb (480,640,3)`；`[PROGRESS] step_counter=1`；exit 0

---

## 明确非声称

- 非正式 five-stage shadow
- 非人体/工具/PPE 语义验证
- 非论文 LIVE 完成
