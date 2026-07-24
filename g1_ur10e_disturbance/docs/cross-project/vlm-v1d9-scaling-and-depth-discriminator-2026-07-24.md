# V1-D9：数据集跨 seed 扩产 + 深度运动判别器（2026-07-24）

两条既定路线的合并执行：S1（seed 泛化扩产）+ S2（相位补全，兼作深度判别器
标定数据）→ D9A（离线特征筛选）→ D9B（规则 v2.1 深度通道）→ D9C（seed 48
留出验证）。

## S1+S2 采集与批量评估

- 3 次单次 Isaac 运行（seed 46/47/48 × mirrored patrol，各 61 帧、4 窗口：
  approach 60–145 / dyn_sweep 170–249 / retreat 325–400 / static_idle 420–465），
  exit 全 0，无重试。
- 链路评估 183 track POST，无 GT 种子、无 VLM。**12/12 窗口跟踪 100% 在
  G1 上（183/183 帧）**——感知层跨 seed、跨相位完全稳定。

### 规则 v2（仅平移通道）成绩

- dyn_sweep 3/3 触发（78.6–81.3 px/s）、static_idle 3/3 拒绝（12.0–16.0 px/s）：
  跨 seed 回归全绿，v1 继续复现 F9/F10 失败。
- 深度窗口 6 个中 3 个因离轴透视平移意外触发（真阳性），3 个漏报
  （13.1–20.1 px/s，与微晃区间 12.0–16.0 重叠）→ **平移率单特征不能分离
  慢速深度运动与微晃**，确认需要缩放域判别。

## D9A：离线特征筛选（0 POST，seed 48 全窗口留出）

标定集：深度真值 5（approach/retreat 46/47 + b2）、横移 5、静止 3、泄漏 1（D3C）。
特征表关键分离：

| 特征 | 漏报深度窗口 | 静止窗口 | 余量 |
|---|---|---|---|
| scale_rate_px_s | 21.5–28.8 | ≤ 14.7 | ~1.2x |
| aspect_change | 0.08–0.27 | ≤ 0.02 | ≥ 2.5x |

判别器：`depth_motion_suspect = scale_rate ≥ 18 AND aspect_change ≥ 0.05`。
**已知残余风险（如实记录）**：D3C 型宽度单边泄漏的 aspect_change（0.27）与
approach 重叠，二者不可分。缓解：(1) 唯一泄漏样本来自已退役的俯视视角，
正视 12/12 窗口从未出现真实泄漏；(2) 误触发动作为 slow_down，属安全侧错误
（损失效率、不损失安全）；(3) 数据集标注仍需人工审查，规则触发不改标签。

## D9B：规则 v2.1（evidence_gated_dynamic_rule_v2_1_depth）

- `window_motion.py` 新增 aspect_change 等特征与 `depth_motion_suspect`；
- 规则新增 `enable_depth_path` 第二触发通道（默认关闭，显式启用），
  motion_bucket 区分 `window_translation` / `window_depth_scale`；
- 单测 22/22 通过（新增深度通道用例 2 个）。

## D9C：seed 48 留出验证 → D9C_HOLDOUT_PASS（4/4 预注册预测确认）

诚实性说明：seed 48 的平移/缩放率在批量输出中已可见；aspect_change
（深度通道核心特征）在本验证前从未对 seed 48 计算过。

| 窗口 | GT | 判决 | 通道 |
|---|---|---|---|
| approach | 动 | 触发 ✓ | 平移（31.1 px/s） |
| dyn_sweep | 动 | 触发 ✓ | 平移（78.6 px/s） |
| retreat | 动 | **触发 ✓** | **深度（scale 29.6，aspect 0.16）** |
| static_idle | 静 | 拒绝 ✓ | —（aspect 0.024 < 0.05） |

**v2.1 全 12 窗口成绩：12/12**（v2 为 9/12，v1 为 4/12）。retreat 类窗口
（v1/v2 双漏）全部由深度通道召回。

## 数据集状态

manifest 3.7.0：新增 12 个 provisional 条目（动态正 3、深度运动正 6、静态负 3），
全部待人工审查；审查材料为每 seed 一张 4 窗口首末帧拼图
（results/paper_demo/v1d9_review_packet_20260724/）。

## 边界

- 深度判别器标定于单场景族（mirrored patrol）+ 单相机；scale 阈值余量仅
  1.2x，跨场景族需继续验证。
- 泄漏-深度不可分性未解决，依赖视角先验与安全侧动作缓解。
- 遮挡相位仍无可用场景。

## 预算

Isaac 运行 3 次（无重试）、track POST 183、VLM 0；D9A/C 均 0 POST。
