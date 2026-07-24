# V1-D3B：Grounding 目标选择评估（②GT 种子诊断 → ③探针矩阵 → ①prompt 修复）

- 日期：2026-07-24
- 结果目录：`results/paper_demo/v1d3b_grounding_eval_20260724/`（不提交）
- 脚本：`GMRobot/scripts/run_v1d3b_grounding_eval.py`
- 服务：GDINO base + SAM2.1 hiera_small + Qwen2.5-VL-7B（远端 L40S，SSH 隧道）
- POST 总数：27，重试：0

## 结论（verdict = GROUNDING_SYSTEMATIC_FAIL + SPARSE_REPLAY_SAM2_FAIL, fail-closed 全程成立）

1. **③ 探针矩阵：GDINO 目标选择失败是系统性的，prompt 工程（本轮测试空间内）无法修复。**
   6 帧（E2K 170/249、E2D 240/310、Dyn-B M1Z9 220/330）× 4 prompt = 24 次 ground，
   **G1 命中 0/24**。
   - P0 "white humanoid robot"、P1 空间约束、P2 形状描述：各 5–6/6 锁定 UR10e 臂区
     （典型框 [332,107,415,241]，而 G1 GT 框在画面底部 [270,373,351,444] 附近）。
   - P3 多类 "humanoid robot . robotic arm" + 非臂后选：6/6 返回近全图大框（other），无判别力。
2. **② GT 种子诊断：目标选择并非唯一瓶颈——稀疏两帧重放会破坏 SAM2 传播。**
   用 E2K step 170 的 G1 GT 投影框喂 `track_init`，SAM2 init 正确贴合 G1
   （[291,372,353,441]）；但跨 79 帧跳到 step 249 后，传播框 [332,371,371,441] 未跟上
   G1 实际左移（GT [223,369,304,443]），mask score 0.265 < 阈值 →
   `score_below_threshold` → 证据被拒 → VLM 保持 static@0.70。**fail-closed 第二层生效。**
   注：稀疏重放下 enrich 速度估计（1475 px/s）不可信，但证据层已先行拒绝，未污染判断。
3. **① 最佳 prompt 全链修复：按预注册规则跳过**（③ 中无任何 prompt 命中 G1，无候选可验证）。
4. **VLM 纪律全程保持**：无有效时序证据时从未宣称 dynamic（static@0.70），0.85 置信门未动。

## 边界与归因

- GT 框仅用于 ② 的目标种子（`diagnostic_only=true`，不得用于端到端声明）和 ③ 的评估标签。
- 运动证据全程 SAM2-only；证据阈值、置信门未改动。
- ② 暴露的 SAM2 失败归因于**固定帧重放协议的 79 帧稀疏跳变**，不等价于生产密集逐帧
  跟踪的缺陷；验证时序链需改用密集帧重放（新提案，未执行）。
- ③ 的 24 次全错归因于 GDINO（`grounding-dino-base`）在本场景对小尺寸 G1 与
  大尺寸 UR10e 的文本判别失败，属感知层系统性局限，为论文分层 fail-closed 架构提供量化证据。

## 分类判据

检测框中心落入 G1 GT 投影框（pad 20 px）→ `g1_hit`；距 UR10e EE 投影 ≤90 px →
`ur10e_region`；否则 `other`。GT 投影来自各 run 的 `body_poses.jsonl` +
`scene_camera_override` 相机模型（cam=[0.45,0,2.7]，640×480）。

## 下一步候选（未执行）

- D3C：密集帧重放（170..249 全帧或每 5 帧）验证 SAM2 传播与时序证据链。
- 感知层替换/微调评估（更大 GDINO、或以 GT ROI 蒸馏的检测器）——超出当前冻结范围，仅记录。
