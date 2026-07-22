# V1-E01-Func-C 单场景采集（2026-07-22）

## 1. Verdict

**VISUAL_SCENE_INTEGRITY_FAIL**（2026-07-23 审计降级；原标记 `CAPTURE_PASS_PROVISIONAL_FUNCTIONAL`）

| 检查 | 结果 |
|---|---|
| asset distinction 预检 | **通过**（`ASSET_DISTINCTION_OK`；非文件名证明） |
| Isaac exit | **0** / steps **0–299**（max_steps=300） |
| camera ready / RGB | **是**（640×480，step 100/200） |
| container_full 可见 | **是**（绿箱 + 内部 packed parts） |
| target ROI ≥2500 px² | **通过**（投影 AABB = **2970**） |
| filled-content 视觉证据 | **是**（ROI 内 non-green dark px：100→323 / 200→309） |
| UR10e / 任务上下文 | **可见** |
| geometry 100–200 全 ALLOW | **通过**（101/101 ALLOW；STOP/SLOW/replan=0） |
| POST / VLM / GDINO / SAM2 | **0**（未调用） |
| Traceback / 新 Xid | **0** / 未见新 Xid |
| labels | `functional` / `provisional` / `reviewer_approved=false` |
| 历史结果覆盖 | **无**（新目录） |
| 正式 capture 次数 | **1** |
| **🛑 frame0 场景完整性** | **FAIL**（白色扇形 — 起始箱 A 的 Part_1..20 散落异常） |

**降级原因**（2026-07-23 审计）：
- frame0 图像中起始箱 A 周围出现白色扇形散落，对应 20 个 Part_* 物理体在初始化时未正确落入 A 槽位。
- 根因：`container.usd` 存在嵌套 RigidBodyAPI（`/Root/Container` 与 `/Root/Container/Ref` 同时 active），Isaac 日志明确警告 "nested RigidBodyAPI produces unpredictable results"。
- 20 个 Part 的 `modify_mass_properties` 在 spawn 时全部失败（当前 spawn 路径未正确解析 Part_1..20 的刚体 prim）。
- 目标箱 B 的 `container_full_visual.usd` 本身渲染正常——问题在**起始箱 A 的物理初始化**，而非视觉资产。

论文口径（候选场景，非模型成功声明）：「视觉上已满或不可用于继续放置的目标容器候选场景。」
**注意**：此场景**不能**进入数据集或 VLM 评估——frame0 即出现物理异常，后续帧虽目标箱 B 可见，但始态已污染。

---

## 2. HEAD / worktree

| 项 | 值 |
|---|---|
| branch | `main` |
| HEAD | `2d3c870642ecc25eb4d3665bccea798c0339d8a5` |
| worktree | **脏**（本轮 Func-C 代码/配置；**未 commit / 未 push**） |
| ahead of origin | 8（沿用基线；本任务不授权 push） |

---

## 3. Image / config / asset SHA

| 项 | 值 |
|---|---|
| image tag | `gmdisturb:e01-func-c-20260722` |
| image Id | `sha256:c2e526961d44119d2ac6ec30079cf58dfd4adab6b8c755fe617765434b31839b` |
| created | `2026-07-22T20:39:49+08:00` |
| 未覆盖历史镜像 | `e01-dyn-a` / `semantic-shadow-v1c0p1` / `b4-p010` |
| config | `g1_ur10e_disturbance/configs/e01_func_c_capture.yaml` |
| config SHA256 | `c4924b16843ed2b262e670fe551cf34e64abbf6c20d8d0f00587d1750b1163a3` |
| safety YAML | `GMRobot/configs/ivj_v1e01_target_container_full.yaml` |
| safety YAML SHA256 | `b30f728b32deb528621ef6e552f2306133eba123f946681b0d1aca5a8731fee8` |
| `container.usd` | `ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9` |
| `container_full.usd`（语义源） | `ff4d02a29701726baedea0dcd9cdc0cba92d7fa5dfa4121468974e495b3e0ba0` |
| `container_full_visual.usd`（spawn-only，gitignore） | `60efbaa11fc845492dcb5e734fe509e20a67e1b9fd7e51c03a65f4b404c83885` |
| `part_5000.usd` | `71fd48abb018275ae5bf9634216898136c028d0c883deb50caa7467481991aa6` |

运行时说明：直接 spawn 原始 `container_full.usd` 会因嵌套 `Part_*` 与场景 `env_.*/Part_N` 正则冲突而失败。本轮使用本地派生的 **visual-only** USD（相对 defaultPrim、无 `/World`、无 physics；内部 `FilledContent_*` 命名），语义预检与 manifest 仍指向 `container_full.usd`。

---

## 4. 改动文件

| 路径 | 作用 |
|---|---|
| `GMRobot/.../shadow/target_full_override.py` | 默认关闭开关 `GMROBOT_V1E01_TARGET_FULL=1`；仅 box_B |
| `GMRobot/.../gmrobot_env_cfg.py` | 启用时 box_B→visual spawn；跳过 grid_B |
| `GMRobot/.../shadow/v1e01_func_c_capture.py` | 预检 / ROI / geometry / manifest |
| `GMRobot/configs/ivj_v1e01_target_container_full.yaml` | 远场 parked hand；log_dir→Func-C |
| `g1_ur10e_disturbance/configs/e01_func_c_capture.yaml` | 文档化 profile |
| `GMRobot/scripts/test_e01_func_c_capture_unit.py` | 离线单测 |
| `GMRobot/scripts/analyze_e01_func_c_capture.py` | 预检+分析 |
| `g1_ur10e_disturbance/scripts/run_e01_func_c_capture.sh` | precheck/smoke/capture/analyze |
| `GMRobot/docker/Dockerfile.e01-func-c` | 薄镜像 |
| `.gitignore` / `GMRobot/.gitignore` | 忽略大型 `container_full_visual.usd` |

**未改**：安全阈值、控制/gate/action/protocol/replan、B0–B4、D1A/D1B 历史配置、默认 camera。

---

## 5. 测试 / smoke

| 项 | 结果 |
|---|---|
| `scripts/test_e01_func_c_capture_unit.py` | **PASS** |
| asset precheck | **PASS**（31 meshes / ~27.5M pts vs empty 1 / ~0.89M；30 Part_*） |
| canonical import | **PASS** |
| 1-step camera smoke | **exit=0**；`scene_rgb` ready；PNG 有效；POST=0；无 Traceback |
| 正式 capture | **一次**；exit=0 |

---

## 6. Exit / steps

| 项 | 值 |
|---|---|
| exit code | `0`（`meta/isaac_exit_code.txt`） |
| steps | `0..299`（300 行 CSV） |
| capture steps | **100 / 200** |
| seed 记录 | `51`（agent 无 `--seed` CLI；写入 `meta/seed_record.json`） |

---

## 7. RGB 路径 / SHA

| step | path | SHA256 |
|---|---|---|
| 0 | `results/paper_demo/v1e01_func_c_capture_20260722/scene/frame_000000_env0.png` | `6e203cc482f1fcb12309ac0586a7665e1749fba3a8c20bea1953fc4ae0a33ba6` |
| 100 | `results/paper_demo/v1e01_func_c_capture_20260722/scene/frame_000100_env0.png` | `0b9583938044ad2aaddd684b3b024933c7d11a8b11aa41e2428912fd4050964b` |
| 200 | `results/paper_demo/v1e01_func_c_capture_20260722/scene/frame_000200_env0.png` | `72b5c1167f59b56d997ccce24346ebcccaf1050e9429f7c04bc633a6462cd89c` |

正常对照：
| step | path | SHA256 |
|---|---|---|
| 0 | `results/paper_demo/v0b1_rgb_capture_20260721/scene/frame_000000_env0.png` | `d2c30b8733343251d3020dab697421da969ac2af70b7cc2221aae41d533a1056` |

frame0 v1e01 vs v0b1 **hash 不同**；v1e01 frame0 出现白色扇形散落（约 187 kB），v0b1 正常（约 174 kB）。

---

## 8. Target / filled ROI 与来源

| 项 | 值 |
|---|---|
| target ROI | bbox `[266,203,364,232]`；area **2970** |
| roi_source | `projected_box_b_aabb`（默认 camera `(0.35,0,2.5)`） |
| filled ROI | bbox `[279,207,351,228]`；area **1606** |
| filled source | `projected_filled_parts_aabb` |
| containment | filled ⊆ target（AABB） |

---

## 9. Filled-content 视觉证据

1. **资产结构**：`container_full.usd` 相对 `container.usd` 多 30 个 Part mesh / ~27M points（预检）。
2. **RGB**：filled ROI 内 non-green dark pixels：step100=**323**，step200=**309**（`filled_roi_non_green_dark_pixels`）。
3. **Spawn 路径**：运行时 `container_full_visual.usd`；manifest `box_B_usd=container_full.usd`。

不使用文件名 “full” 代替视觉证据；红球/手 **不作为**功能语义证据（far-field parked hand `[0.25,-0.75,0.60]`）。

---

## 10. Geometry 100–200 完整分布

| 项 | 值 |
|---|---|
| window | `[100, 200]` inclusive |
| n_steps | **101** |
| ALLOW / STOP / SLOW | **101 / 0 / 0** |
| replan | **0** |
| held_critical / static_warning / dynamic_ttc（reason） | **0** |
| dist_min / mean（envelope） | **0.386** / **0.413** m |
| margin_to_warn / hard | **+0.226** / **+0.256** m（阈值未改：warn=0.16 / hard=0.13） |
| TTC finite min（数值，非触发） | **2.66** s（> warn/hard；reason 全为 `allow`） |

---

## 11. 完整 episode gate 摘要

| gate | count |
|---|---|
| ALLOW | 274 |
| SLOW_DOWN | 24 |
| STOP | 2 |

非 ALLOW 全部发生在 **窗口外** early steps（约 1–55，`dynamic_ttc*`）；**未**因此调参/重跑。窗口 100–200 仍全 ALLOW。

---

## 12. Task phase

| 项 | 值 |
|---|---|
| outcome | `timeout@298/7521`（整段一致） |
| task_time_step last | 297 / max 7420 |
| hand motion | 无（start=end far-field；`hold_far=true`） |
| D1B blocker | **未启用** |

---

## 13. POST=0

`meta/post_count_proof.json`：`post_count=0`；无 VLM/perception/five-stage client 初始化行；`traceback_count=0`。

---

## 14. Xid

`meta/xid_before_capture.txt` / `xid_after_capture.txt`：`nvidia-smi` Xid 查询不可用；dmesg 未见本轮新 `NVRM: Xid`。stdout 无 Traceback。

---

## 15. Provisional 标签边界

| 字段 | 值 |
|---|---|
| `expected_risk_type` | `functional` |
| `label_status` | `provisional` |
| `reviewer_approved` | `false` |
| `not_vlm_positive` | `true` |
| `not_accepted` | `true` |
| `ready_for_vlm_screen` | `false` |

---

## 16. 场景完整性缺陷（2026-07-23 审计新增）

| 证据 | 值 |
|---|---|
| frame0 散落 | **白色扇形**（起始箱 A 周围约 20 Part 未落入槽位） |
| container.usd 嵌套刚体 | `/Root/Container` + `/Root/Container/Ref` 同时 RigidBodyAPI enabled |
| Isaac 警告 | nested RigidBodyAPI produces unpredictable results |
| modify_mass_properties | Part_1..20 全部失败（spawn 未解析到正确 prim） |
| container_full_visual.usd | 0 rigid / 0 collision（visual-only，正常） |
| box_A spawn | 使用 container.usd（嵌套刚体）；受嵌套影响 |
| box_B spawn | 使用 container_full_visual.usd（visual-only kinematic）；不受影响 |

**结论**：目标箱 B 视觉正常，但起始箱 A 及其 20 Parts 物理初始化异常。step 100/200 的"正常"外观是仿真收敛后的结果——始态（frame0）已污染。此场景**不能**作为 VLM 评估正样本。

---

## 17. 是否具备进入人工标签审查

**否**：frame0 完整性缺陷意味着起始状态不可信。需先修复 USD/init 问题并重新采集。

**下一步不应自动做**：VLM 筛选、SAM2、Dyn-B、commit/push。

---

## 18. git status / diff

```
 M .gitignore
 M GMRobot/.gitignore
 M GMRobot/source/GMRobot/GMRobot/tasks/manager_based/gmrobot/gmrobot_env_cfg.py
?? GMRobot/configs/ivj_v1e01_target_container_full.yaml
?? GMRobot/docker/
?? GMRobot/scripts/analyze_e01_func_c_capture.py
?? GMRobot/scripts/test_e01_func_c_capture_unit.py
?? GMRobot/source/GMRobot/GMRobot/shadow/target_full_override.py
?? GMRobot/source/GMRobot/GMRobot/shadow/v1e01_func_c_capture.py
?? g1_ur10e_disturbance/configs/e01_func_c_capture.yaml
?? g1_ur10e_disturbance/docs/cross-project/vlm-v1e01-func-c-capture-2026-07-22.md
?? g1_ur10e_disturbance/docs/cross-project/vlm-v1e01-func-c-capture-2026-07-22.json
?? g1_ur10e_disturbance/scripts/run_e01_func_c_capture.sh
```

`git diff --stat`（已跟踪文件）：3 files, +37/−9。results 目录 gitignored，未纳入版本库。

---

## 停止边界

- 不执行 VLM 筛选
- 不执行 SAM2
- 不执行 Dyn-B
- 不提交 / 不 push；等待单独工作区审查
