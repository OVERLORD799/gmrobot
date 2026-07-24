# V1-D3C：密集帧 GT 种子 SAM2 重放（VLM 反馈边界评估收官）

- 日期：2026-07-24
- 采集目录：`results/paper_demo/v1d3c_dyn_c_dense_capture_20260724/`（不提交）
- 评估目录：`results/paper_demo/v1d3c_dense_replay_eval_20260724/`（不提交）
- 脚本：`GMRobot/scripts/run_v1d3c_dense_replay.py`
- POST：18（17 track + 1 analyze），重试：0

## 采集（单次 Isaac 运行）

完全克隆 E2K 身份：镜像 `gmdisturb:e01-dyn-c-motion-preflight-m1e2j1-20260724`、seed 44、
`mirrored_outer_lateral_patrol`、同 config、同相机合同（[0.45,0,2.7]，contract_match=true）。
仅将 capture steps 扩为 170..245 每 5 帧 + 249，共 17 帧。硬化 runner exit=0，无 Traceback，
17/17 帧齐全。**确定性核对：step 170/249 的 g1_root 与 ur10e_ee 与 E2K 逐位一致（maxdiff=0）**，
故 E2K 的人工动态标签与 GT 投影框对本采集同样成立。

## 评估结果（verdict = D3C_DENSE_TEMPORAL_CHAIN_FAIL，预注册门禁）

| 门禁 | 结果 |
|---|---|
| G1 追踪在目标上 ≥80% | **FAIL**（8/17） |
| G2 证据有效 | PASS（score 0.947，speed 160 px/s） |
| G3 VLM dynamic ≥0.85 | **FAIL**（static@0.70） |
| FC 无有效证据不宣称 dynamic | PASS（全程成立） |

### 发现 1：SAM2 长时程漂移（新失败模式）

GT 种子在 step 170 正确贴合 G1（IoU 0.68）。G1 左移（GT cx 310→264），但掩码框
右缘持续膨胀（353→418），step 205 起 IoU≤0.21，step 210 起完全脱靶（IoU=0），
锁在静态场景内容上。**密集帧（每 5 步）不能修复漂移**。

### 发现 2：证据层盲区（论文关键发现）

漂移后的轨迹 mask score 高达 0.947、速度 160 px/s、会话连续——现有证据校验
（score≥0.5 / speed≥10 / continuity）**全部通过**。即：证据层无法识别"自信地
跟错对象"，valid-but-wrong 证据进入了 VLM prompt。

### 发现 3：VLM 层意外兜底 + 反馈边界确认

prompt 已注入 valid 时序证据（明示 160 px/s、tracking），Qwen2.5-VL-7B 仍输出
static@0.70，keywords 仅 "robotic arm, containers, placement"（未识别人形机器人）。
两面性：
- 兜底面：VLM 未盲信注入证据，错误证据未升级为 dynamic 误报，系统净行为仍 fail-closed；
- 边界面：**在 D3A/D3B/D3C 全部实验中，VLM 从未产出 dynamic≥0.85**——当前
  prompt v2 + Qwen2.5-VL-7B 无法把文本时序证据转化为动态风险判定，VLM 层是
  动态正样本端到端判定的最终瓶颈。

## 四层失败模式量化汇总（D3A+D3B+D3C）

| 层 | 失败模式 | 证据 |
|---|---|---|
| GDINO | 目标选择系统性失败 | 0/24 命中 G1（D3B③） |
| SAM2 | 稀疏跳变传播失败；密集帧长时程漂移 | score 0.26 被拒（D3B②）；8/17 脱靶（D3C） |
| 证据层 | 无法检测高置信漂移 | 0.947 分通过校验（D3C） |
| VLM | 对文本时序证据不敏感 | 三轮实验 0 次 dynamic≥0.85 |

净结论：五阶段管线当前**无法端到端产出动态风险真阳性**，但每一处失败均保持
fail-closed（无一次误报 dynamic）。这为论文的分层安全论证提供了完整的量化负结果链。

## 边界

- GT 框仅用于初始种子与评估标签（diagnostic_only），运动证据 SAM2-only；
- 证据阈值（0.5/10px/s）与置信门 0.85 未改动；
- 单次采集 + 单次评估，无重试；B0–B4 冻结未触碰。
