# V1-D4C：prompt v3 正式化 + F7 修复 + 成对重放 + 敏感度因子分解

- 日期：2026-07-24
- 结果目录（均不提交）：`v1d4c_paired_replay_20260724`、`v1d4c1_speed_titration_20260724`、`v1d4c2_entity_speed_factorization_20260724`
- POST：3 + 3 + 2 = 8，重试：0；track 数据全部离线复用 D3C，无新感知 POST

## 一、代码交付

1. **prompt v3**（`vlm/prompt_v3.py`，版本 `five_stage_safety_v3_temporal_directive`）：
   与 v2 唯一差异是在证据 JSON 之后追加 D4B V6 验证过的证据信任指令（措辞、位置
   逐字冻结以保可比性）。注册进 `ALLOWED_PROMPT_VERSIONS`。模块文档中写明
   **安全耦合**：v3 只能用于已过漂移拒绝（D4A）的证据。
2. **F7 修复**（`temporal_evidence.py`）：`ENTITY_CLASSES` 新增 `humanoid`；
   别名表加 `humanoid robot/humanoid → humanoid`；裸 "robot" 显式映射为
   `unknown`（原先经子串匹配误归 `robotic_arm`）；别名排序保证
   "industrial robotic arm" 等回归行为不变。
3. 单测 8 项新增全过；时序证据/漂移/门禁相关 47 项回归全过。

## 二、D4C 成对重放（3 臂，固定 249 帧）

| 臂 | 证据 | VLM (prompt v3) | 门禁 |
|---|---|---|---|
| P1 成对栈 | D3C 真实漂移轨迹 + D4A 标记 → `track_drift_suspect` 拒绝 | static@0.70 | **G1 特异性 PASS** |
| P2 对照（无 D4A） | 同一漂移证据，valid=true | **dynamic@0.90 = 被演示的假阳性** | **G2 PASS：单用指令不安全，D4A 必要性实证** |
| P3 完美跟踪探针 | GT 导出运动学（35.5 px/s，humanoid），valid=true | static@0.70 | **G3 敏感性 FAIL** |

P1+P2 是论文最想要的一对：同一份错误证据，有无漂移拒绝直接决定假阳性是否发生。
P3 揭示指令遵从并非字面的（"≥10 px/s 必须 dynamic"未被执行）。

## 三、D4C.1/.2：敏感度边界因子分解（diagnostic_only）

全因子记录（每格 n=1，无重复采样，受不重试政策约束）：

| entity \ speed | 35.5 | 50 | 80 | 120 | 160 |
|---|---|---|---|---|---|
| humanoid | static | static | static | static | **static** |
| unknown | — | — | — | **static** | **dynamic@0.9**（D4B V6） |
| robotic_arm | — | — | — | — | **dynamic@0.9**（D4C P2） |

结论：**dynamic 仅出现在（entity≠humanoid 且 speed=160）的狭窄口袋**。
- 速度维度：unknown 实体下 120→160 之间存在隐式跳变，与指令宣称的 10 px/s
  阈值相差一个数量级；
- 实体维度：F7 修复引入的 `humanoid` 类反而使模型在 160 px/s 也保持 static
  ——模型疑似把"移动的人形机器人"语义化为非危险主体；
- 可复现性注记：每格单样本，dynamic 共出现 2 次且均在同一口袋，模式一致但
  未做重复采样验证。

## 四、净结论（F8，已入台账口径）

prompt v3 的指令能解锁动态判定，但**遵从是脆弱且非字面的**：存在速度×实体
交互的隐式判定边界。当前 VLM 层不构成可靠的动态风险分类器；可靠化路径不在
提示工程内（候选：VLM 微调，或把 valid 证据的 dynamic 判定下沉为符号规则、
VLM 仅做语义描述）。成对栈的特异性一侧（D4A 拒绝 + 无假阳性）已实证成立。

## 五、边界

- P3 与滴定/因子分解均为 GT 导出或合成探针证据，diagnostic_only，永不作为
  数据集标签或端到端声明；P1/P2 的轨迹与证据来自 D3C 真实 SAM2 记录；
- 置信门 0.85、证据阈值未动；生产默认路径仍是 prompt v2（v3 需显式选用）；
- B0–B4 冻结未触碰。
