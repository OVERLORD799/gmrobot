# V1-D4：VLM 反馈边界系列发现台账（D3A/D3B/D3C/D4A/D4B）

- 日期：2026-07-24
- 性质：汇总台账 + 两项新增工作（D4A 漂移检测、D4B VLM 敏感度消融）的正式记录。

## 一、失败模式台账（全部有原始证据、零重试）

| # | 层 | 发现 | 证据来源 |
|---|---|---|---|
| F1 | GDINO | 目标选择系统性失败：4 种 prompt × 6 帧 × 3 场景，G1 命中 0/24，全部锁定 UR10e 臂区或返回近全图框 | D3B③ |
| F2 | SAM2 | 稀疏跳变（79 帧）传播失败，score 0.26 被证据层拒绝 | D3B② |
| F3 | SAM2 | 密集帧（每 5 步）长时程漂移：GT 种子正确贴合后 8/17 帧内脱靶，掩码泄漏到静态内容且 score 高达 0.947 | D3C |
| F4 | 证据层 | 盲区：score/speed/continuity 校验对"自信跟错"的轨迹全部放行，valid-but-wrong 证据进入 VLM prompt | D3C |
| F5 | VLM | prompt v2 下对时序证据完全不敏感：速度 15→300 px/s、实体标签、任务上下文全变体均 static@0.70（0/6 越过 0.85 门） | D3A/D3C/D4B |
| F6 | VLM | 意外兜底：不盲信注入证据，错误证据未升级为 dynamic 误报——系统净行为全程 fail-closed，零误报 | D3C/D4B |
| F7 | 证据 schema | `ENTITY_CLASSES` 无 humanoid 类；标签 "robot" 经别名规则错误归一化为 `robotic_arm`（"robot" ⊂ "robotic arm" 子串匹配），人形机器人在证据合同中不可表达 | D4B 代码审查 |

## 二、D4A：证据层漂移检测（修复 F4）

原理：掩码泄漏的几何签名是"框变尺寸"，刚体平移是"框移动不变形"。
实现：`GMRobot/vlm/track_drift.py`（`assess_box_drift`，尺寸比带宽 [0.85, 1.15] +
扩张 ≥8 px），并在 `TemporalTrackEvidence` 增加 `drift_suspect` 字段（默认 False，
向后兼容），`validate_temporal_evidence` 对其拒绝（`track_drift_suspect`）。

离线验证（真实数据回放，零 POST）：

| 序列 | 结果 |
|---|---|
| D3C 漂移轨迹（17 框） | **step 185 即标记**（比 IoU 归零的 step 210 早 25 步），max ratio 1.39 |
| D3C GT 完美跟踪代理（17 框） | 零误报（max ratio 1.05，扩张 3.9 px） |
| D3B 稀疏漂移对（2 框） | 标记（ratio 0.63） |

单测 8/8 通过；既有时序证据测试 43 项无回归。
**边界**：阈值仅在单场景（Dyn-C 重放）上标定，属初步标定；跨场景使用前须重新校验。

## 三、D4B：VLM 时序证据敏感度消融（定位 F5 根因）

固定图像（E2K step 249），仅变化 prompt 中的证据内容，7 个变体各 1 次 POST：

| 变体 | 证据内容 | 结果 |
|---|---|---|
| V0 | 无证据（基线） | static@0.70 |
| V1 | D3C 真实证据回放（160 px/s，实体=robotic_arm） | static@0.70 |
| V2 | 同速，humanoid 标签（实体=unknown） | static@0.70 |
| V3 | 300 px/s，接近方向 | static@0.70 |
| V4 | 15 px/s 慢速 | static@0.70 |
| V5 | 任务上下文=transit/transport_active | static@0.70 |
| **V6** | **V2 证据 + 一段"信任已验证追踪器"显式指令** | **dynamic@0.90，keywords 出现 "humanoid robot"、"motion tracking"** |

**结论：F5 的根因不是 Qwen2.5-VL-7B 的能力，而是 prompt v2 合同——它把证据作为
数据呈现但从未指示模型如何使用。一段指令（prompt v3 候选）即解锁动态判定。**

关键耦合：启用 V6 式指令后 VLM 将信任一切 valid 证据——包括 D3C 那种
valid-but-wrong 漂移证据。因此 **D4B（敏感性）与 D4A（特异性）必须成对部署**：
指令让真阳性成为可能，漂移拒绝阻止假阳性。这是论文分层论证的核心结构。

## 四、边界与政策

- V2–V6 为合成探针证据，`diagnostic_only`，永不作为数据集标签或端到端声明；
- V1 为 D3C 真实证据回放；
- 生产 `prompt_v2` 模块未改动（指令仅在实验脚本内追加）；置信门 0.85、
  证据阈值（0.5 / 10 px/s）未变；B0–B4 冻结未触碰；
- 后续（未执行）：prompt v3 正式化 + F7 schema 修复（增加 humanoid 实体类）+
  D4A/prompt v3 成对端到端重放。

## 五、增补（同日 D4C 系列执行后）

上述"后续"三项已全部执行（见 `vlm-v1d4c-paired-replay-prompt-v3-2026-07-24.md`），
并新增发现：

| # | 层 | 发现 | 证据来源 |
|---|---|---|---|
| F8 | VLM | prompt v3 指令遵从脆弱且非字面：存在速度×实体交互的隐式判定边界（dynamic 仅出现在 entity≠humanoid 且 speed=160 的口袋；宣称的 ≥10 px/s 规则被忽略；humanoid 实体类在 160 px/s 仍被压制为 static） | D4C P3 / D4C.1 / D4C.2 |

D4C 成对重放同时实证：同一份漂移错误证据，有 D4A 拒绝 → static（无假阳性），
无 D4A → dynamic@0.90（假阳性）。特异性一侧闭环成立；敏感性一侧（可靠真阳性）
仍开放，候选路径为 VLM 微调或将动态判定下沉为符号规则。

## D7A/D7B 增补（2026-07-24，详见 vlm-v1d7ab-boundary-batch-and-window-motion-2026-07-24.md）

- **F8**（vlm，D4C.1/2）：VLM 动态服从性脆弱且非字面：仅在 entity≠humanoid 且 speed=160 的窄口袋输出 dynamic@0.90；无视既定 ≥10 px/s 规则；对 humanoid 实体抑制 dynamic。
- **F9**（证据层 D4A，D7A）：尺寸带漂移启发式不泛化——步态/深度/拖尾等合法尺寸变化被误判漂移，3/3 真动边界窗口 fail-closed 漏报。
- **F10**（证据层速度，D7A b3）：末帧瞬时速度阈值 10 px/s 低于 G1 idle 平衡微晃（瞬时 25–35 px/s），产生静止误报。
- **F11**（证据层 v2，D7B）：窗口首末框刚体分解（平移 vs 缩放）以 25 px/s 阈值分离真动（43–69）与微晃（14.7），双侧 ~1.7x 余量；深度运动缩放主导，保持 fail-closed。离线 5/6 正确（v1 仅 1/6）。
