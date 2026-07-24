# V1-D7A/D7B：边界相位批量采集 + 窗口聚合运动证据（2026-07-24）

## 目的

把 D6A 打通的正视相机动态真阳性链路扩产为数据集，并用边界相位（反向扫掠、深度运动、静止负样本、跨轨迹）压力测试证据层的泛化性。

## D7A：4 个边界采集（各恰好一次 Isaac 运行，无重试）

相机与 D6A 完全一致：pos=(-2.0,-0.15,-0.05)，rot=(1,0,0,0)，正视 +X。
种子提示词沿用 D6A 最优 P3：`humanoid robot . robotic arm`。GT 仅用于评估标签，不用于种子。

| 采集 | 场景/seed | 窗口 | 相位 | GT |
|---|---|---|---|---|
| b1_reverse_sweep | mirrored / 44 | 250–315 | lateral_positive_sweep_mirror（vy=+0.24，与 E2K 窗口反向） | 动 |
| b2_retreat_depth | mirrored / 44 | 325–400 | retreat（vx=−0.30，朝相机深度运动） | 动 |
| b3_static_idle | mirrored / 44 | 420–465 | idle（指令速度 0，仅平衡微晃） | 静 |
| b4_outer_traj | outer / 43 | 165–245 | Dyn-B 外侧车道正向扫掠（跨轨迹族） | 动 |

预注册预期（运行前写入评估脚本 docstring）：b1/b4 触发、b2 可能暴露 D4A 对合法接近性尺寸增长的盲区、b3 必须不触发。

遮挡相位不可用：现有脚本化场景中 G1 不会从正视视角穿越工作台后方，如实注明，不伪造。

### 采集结果

4/4 runner exit=0，57 帧全部落盘。

### 生产链评估（run_v1d7a_batch_chain_eval.py，57 track POST，0 VLM）

**感知层完美泛化**：4 个采集 GDINO 种子 + SAM2 跟踪全部 100% 在 G1 上
（14/14、16/16、10/10、17/17）。N1 稳健性确认。

**v1 证据层（末帧瞬时速度 + D4A 尺寸带漂移门）4/4 判决错误**：

| 采集 | GT | v1 结果 | 原因 |
|---|---|---|---|
| b1 | 动 | miss_fail_closed | D4A 误判漂移（尺寸比 1.27 出带） |
| b2 | 动 | miss_fail_closed | D4A 误判漂移（合法接近致尺寸比 1.30） |
| b3 | 静 | **false_positive** | 平衡微晃瞬时速度 25 px/s > 10 px/s 阈值 |
| b4 | 动 | miss_fail_closed | D4A 误判漂移（步态+部分拖尾致 1.51） |

## 新发现（并入发现台账）

- **F9**：D4A v1 尺寸带启发式不泛化。步态外观变化、深度接近、部分拖尾都会
  触发出带标记，导致 3/3 真动边界窗口 fail-closed 漏报。D4A 在其标定窗口
  （D3C 单场景横移）之外把"合法尺寸变化"与"掩码泄漏"混为一谈。
- **F10**：末帧瞬时速度阈值 10 px/s 低于 G1 idle 平衡微晃幅度（瞬时 25–35
  px/s），产生静止误报。瞬时速度本身是噪声敏感的证据形式。
- **F11**：首末帧框变化的刚体分解（平移分量 vs 缩放分量）可分离真动与微晃：
  真动横移平移率 43–69 px/s，微晃 14.7 px/s，阈值 25 px/s 两侧各 ~1.7 倍
  余量。深度运动（b2）平移率仅 14.5、缩放率 28.8——缩放与泄漏不可分，
  按 fail-closed 保留为已知局限。

## D7B：窗口聚合运动证据 v2（纯离线，0 新增 POST）

模块：`GMRobot/vlm/window_motion.py`（`assess_window_motion`）。
分解：dL=L1−L0、dR=R1−R0，平移=(dL+dR)/2，缩放=|dR−dL|/2（y 同理）。
判定：平移率 ≥ 25 px/s → dynamic；缩放不作为触发条件（泄漏歧义，fail-closed）。
单测 6/6 通过（test_window_motion_unit.py）。

### 六窗口离线对比（v1d7b_report.json）

| 窗口 | GT | 平移率 px/s | v2 判决 | v1 判决 |
|---|---|---|---|---|
| d6a_front_lateral | 动 | 69.2 | true_positive | true_positive |
| b1_reverse_sweep | 动 | 43.4 | true_positive | miss |
| b2_retreat_depth | 动 | 14.5 | miss_fail_closed（预注册局限） | miss |
| b3_static_idle | 静 | 14.7 | true_negative | **false_positive** |
| b4_outer_traj | 动 | 47.2 | true_positive | miss |
| d3c_topdown_leak | 动（场景） | 40.3 | true_positive | drift-rejected |

**v2 正确 5/6，v1 正确 1/6。** 唯一残余错误是预注册的深度运动局限，且方向安全（漏报 fail-closed，非误报）。

## 边界与限制

- v2 阈值 25 px/s 标定于本批 6 个窗口（2 相机、2 轨迹族、4 相位），余量 ~1.7x；
  跨场景推广前需在新采集上前瞻验证。
- v2 尚未接入生产规则（D5A 仍用 v1 证据栈）；接入需一次前瞻性在线验证。
- 深度运动检测开放：候选方向为对称缩放判别器或深度通道。
- b2/b3 的 GT 标签来自脚本化相位表+body pose，未经人工帧审查。

## 数据集状态

manifest 升至 3.5.0：新增 4 个 provisional 条目（b1/b4 动态正候选、b3 静态负候选、b2 深度边界候选），全部 `provisional_pending_human_review`，待人工审查后方可计入正样本组。

## 预算与身份

- Isaac 运行：4（各一次，无重试）；POST：57（全部 SAM2 track，0 VLM）；D7B 0 POST。
- 镜像：gmdisturb:e01-dyn-c-motion-preflight-m1e2j1-20260724（B0–B4 未触碰）。
