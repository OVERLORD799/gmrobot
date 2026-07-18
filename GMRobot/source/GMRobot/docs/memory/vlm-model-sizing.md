---
name: vlm-model-sizing
description: Why Qwen2.5-VL-7B is the minimum viable VLM size and tradeoffs of going smaller
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

当前 VLM 后端为 Qwen2.5-VL-7B-Instruct 4-bit NF4（~6.5GB 显存，~850ms 推理），部署在专用 gm-ai-server（L40S 48GB，仅用 ~9.3GB）。

**可以更小，但有代价：**
- Qwen2.5-VL-3B（~3GB，~400ms）：JSON 一致率可能降至 85-90%（不满足 >95% 硬约束）
- InternVL2-2B（~2GB，~300ms）：中文场景理解弱于 Qwen
- SmolVLM-256M/2B（<2GB，<200ms）：JSON 结构化输出几乎不可靠

**7B 是最低可接受规模的原因不显显存（L40S 远未用满），而是 JSON 结构化输出和零样本安全场景理解对模型规模有硬需求。**

**最优降级方案（文档已预留）**：Fast/Slow 双模型路由——2B/3B 处理高频 Grasp Supervisor 和 Scene Inventory，7B 处理低频 Stage 1/3/4 推理。需实现 `VLMRouter`（Phase 3 MVP 故意推迟的后续分支实验）。

**Why:** 设计 VLM 流水线或考虑成本优化时，不应盲目追求更小模型。

**How to apply:** 若讨论模型替换，首先验证 JSON 一致率 ≥95% 和关键词召回率 ≥85%。双模型路由优先于全球 7B→3B 直接替换。
