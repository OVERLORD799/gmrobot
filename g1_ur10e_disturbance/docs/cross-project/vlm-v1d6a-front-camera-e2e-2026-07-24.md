# V1-D6A：正视相机验证 + 项目首个无 GT 端到端动态真阳性

- 日期：2026-07-24
- 采集：`results/paper_demo/v1d6a_dyn_c_front_camera_capture_20260724/`（不提交）
- 评估：`results/paper_demo/v1d6a_front_camera_eval_20260724/`（不提交）
- 脚本：`GMRobot/scripts/run_v1d6a_front_camera_eval.py`
- POST：26（8 ground + 17 track + 1 analyze），重试：0
- verdict = **D6A_FRONT_CAMERA_E2E_DYNAMIC_TRUE_POSITIVE**

## 一、相机合同 v2（实验性，不改动冻结的俯视合同）

单次 Isaac 采集，物理身份与 E2K/D3C 完全一致（同镜像/seed 44/mirrored 场景/17 个
capture steps），仅相机改为正视：pos=(-2.0,-0.15,-0.05)，rot=(1,0,0,0)（+X 前向，
CLI 覆盖，contract_match=true）。**物理确定性验证：全部 17 步、全部链接位姿与 D3C
数值最大差 = 0**——相机是纯被动渲染，既有人工标签与 GT 对本采集直接成立。
正视图中 G1 呈典型人形剪影，约 150×356 px（对比俯视约 80×75 px 团块）。

## 二、Phase G：grounding 探针 —— 视角根因假设被证实

D3B 同款 4 prompt × 2 帧（170/249），判据同 D3B（GT 投影框中心命中；投影经
UR10e 夹爪与 G1 躯干两个独立地标经验校准）：

| | 俯视（D3B 基线） | 正视（D6A） |
|---|---|---|
| G1 命中 | **0/24** | **8/8** |
| 最高分 | ~0.35（错误目标） | **0.81**（"humanoid robot" 正中 G1） |

同一 checkpoint、同一 prompt、同一物理轨迹，只换视角——**F1 的主因是俯视视角
出分布，不是 GDINO 能力缺陷**。P3 多类 prompt（"humanoid robot . robotic arm"）
效果最好（0.66/0.81），两类各归其位。

## 三、Phase T：生产式全链 —— 无 GT 参与的端到端真阳性

种子 = 文本 prompt（P3，无任何 GT 框），链路全为生产组件：

| 环节 | 结果 |
|---|---|
| GDINO 文本种子 → SAM2 密集跟踪（17 帧） | **17/17 在 G1 上**（GT 仅用于事后评估） |
| D4A 漂移评估 | 未标记（max size ratio 1.075，带宽内）——**跨视角无误报** |
| 证据校验 | valid：score 0.951，speed 552 px/s*，bucket R，**canonical_entity=humanoid（F7 修复生效）** |
| D5A 规则 | **触发 dynamic**，gate_confidence=0.951，action=slow_down |
| VLM 标注（无否决权） | static@0.8，但关键词/实体首次出现 "humanoid robot"，场景描述正确；建议 "alert" 被规则地板正确压制为更严的 slow_down |

\* 速度为末段瞬时估计（245→249 间隔 0.067 s），逐帧噪声大（100–575 px/s）但全程
高于 10 px/s 下限；窗口均速约 68 px/s。

**END_TO_END_DYNAMIC_TRUE_POSITIVE = true**：这是全项目第一次在无任何 GT 参与的
生产链路上得到动态风险真阳性，同时 VLM 的 static 输出被规则权限合同正确旁路——
D5A 架构的敏感性缺口在正确感知输入下闭合。

## 四、论文叙事更新

F1（GDINO 0/24）的归因从"感知模型系统性失败"修正为"**部署视角出分布**"：
同一模型在人形剪影可见的视角下 8/8 命中。修复不需要微调、不需要换模型，
需要的是**感知视角与语义先验的匹配**——这本身是分层安全系统设计的一条结论。
双相机架构就此成立：俯视 = 几何门禁/GT 权威视角，正视 = 语义感知视角。

## 五、边界

- GT 仅用于评估标签（Phase T 种子为纯文本）；GT 框仅含 8 个上身链接（腿部无记录），
  分类判据 pad 40 px 已计入；投影为两地标经验校准（非解析推导，文档如实标注）；
- 单场景单视角位姿的结果；跨场景泛化、遮挡相位（G1 走到工作台后方）未测；
- 正视相机的已知边界：朝相机方向的深度运动像素位移小，px 速度证据会衰减
  （本场景巡逻为横向，不受影响）；
- 冻结项全部未动：俯视相机合同、证据阈值、0.85 语义门、B0–B4。
