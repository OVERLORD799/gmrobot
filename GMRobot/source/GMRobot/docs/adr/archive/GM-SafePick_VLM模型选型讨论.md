# 讨论 2026-06-15 VLM 模型选型（归档）

> **归档说明（2026-06-22）**：早期选型讨论记录，**决策已锁定**：Qwen2.5-VL-7B 4-bit + gm-ai-server 专用拓扑。现行规范见 [Layer 3 §4](../../GM-SafePick_Layer3_VLM推理增强层.md#4-vlm-模型选型指标)、[项目进展 §7.5](../../GM-SafePick_项目进展与遗留问题.md)、[AI 服务器部署](../../GM-SafePick_AI服务器部署.md)。
>
> 背景：GM-SafePick 项目计划将状态机控制器升级为 VLM 驱动的安全推理系统，基于论文 *Proactive Physical Safety Reasoning for Robot Manipulation*。本文记录了各方案的对比与决策过程。
>
> **文档对齐**：视觉输入规格以 [`GM-SafePick_添加相机技术文档.md`](../../GM-SafePick_添加相机技术文档.md) §5 为准；项目场景与任务定义以 [`README.md`](../../../../README.md) 为准。

---

## 1. 需求分析

### 1.1 VLM 在管线中的职责

论文的五阶段推理管线中，VLM 承担以下职责：

| 阶段 | VLM 职责 | 精度要求 |
|------|---------|:-------:|
| Stage 1: 场景分析 | 分析安全场景，生成 grounding 关键词 | 低（定性分析） |
| Stage 3: 风险预测 | 预判不安全后果 | 低（逻辑推理） |
| Stage 4: 动作建议 | 输出干预建议（pause/slow_down/replan） | 低（决策） |

**关键结论**：VLM 不负责连续运动控制，也不直接回归 3D 坐标。只有 Stage 2（Grounding DINO + SAM2 视觉定位）涉及高精度检测，但那部分不由 VLM 完成。

### 1.2 非功能需求

| 需求 | 要求 |
|------|------|
| 延迟 | 检测到风险 2 秒内触发干预（论文指标） |
| 部署 | 可在 gpufree RTX 4090 上运行 |
| 输出格式 | 结构化 JSON（pick/place 序列或安全判决） |
| 视觉输入 | `obs["camera"]["scene_rgb"]`：640×480 RGB，`uint8`（见相机文档 §5） |

---

## 2. 候选模型对比

### 2.1 模型概览

| 模型 | 参数量 | 运行所需显存 | 部署方式 | JSON 输出能力 | 适用阶段 |
|------|--------|-----------|---------|:-----------:|:-------:|
| GPT-4o | 未知（闭源） | N/A（API） | 云端 API | ⭐⭐⭐⭐⭐ | Stage 1, 3, 4 |
| Qwen2.5-VL-7B | 7B | ~16 GB (FP16) / ~8 GB (4-bit) | 本地推理 | ⭐⭐⭐⭐ | Stage 1, 3, 4 |
| Qwen2.5-VL-72B | 72B | ~140 GB (FP16) | 不可行 | ⭐⭐⭐⭐⭐ | — |
| Claude 4 Sonnet | 未知（闭源） | N/A（API） | 云端 API | ⭐⭐⭐⭐⭐ | Stage 1, 3, 4 |
| Gemini 2.5 Pro | 未知（闭源） | N/A（API） | 云端 API | ⭐⭐⭐⭐ | Stage 1, 3, 4 |

### 2.2 GPT-4o（云端 API 方案）

**优点**：
- 结构化输出能力最强（支持 `response_format` JSON Schema）
- 场景理解准确
- 无需本地 GPU 资源
- 多模态能力强（图像+文本）

**缺点**：
- 需网络连接（gpufree 需确认是否能访问 OpenAI API）
- 每次推理有 API 成本
- 延迟受网络影响（中国区域可能不稳定）
- 不适用需离线运行的场景

### 2.3 Qwen2.5-VL-7B（本地推理方案）

**优点**：
- 本地运行，无网络依赖
- 7B 模型可在 RTX 4090 (24GB) 上 4-bit 量化运行
- 中文场景理解好
- 开源可定制

**缺点**：
- 需要 8–16 GB 显存（与 Isaac Sim 争抢）
- JSON 输出格式偶尔不稳定
- 推理延迟 0.5–2s（可通过缓存/批处理缓解）
- 场景理解略逊于 GPT-4o

**推理延迟参考（单帧 640×480）**：

| 量化方式 | 显存 | 延迟 |
|---------|:---:|:---:|
| FP16 | ~16 GB | ~1.5 s |
| 4-bit GPTQ | ~8 GB | ~1.0 s |
| 4-bit AWQ | ~8 GB | ~0.8 s |

### 2.4 Claude 4 Sonnet（云端备选）

**优点**：
- 推理能力极强（适合安全风险推理）
- 输出风格可控

**缺点**：
- 需要 API 密钥
- 网络依赖
- 延迟相对较高

---

## 3. 方案推荐

### 第一期（快速原型）：GPT-4o 或 Qwen2.5-VL-7B

**推荐方案：Qwen2.5-VL-7B-Instruct（4-bit AWQ）**

理由：
1. gpufree RTX 4090 (24GB) 可以同机运行，无需额外 GPU
2. 4-bit 量化后约 8 GB 显存，Sim 约 8-12 GB，总计不超过 24 GB
3. 开源、可定制、无网络依赖
4. 如果是 Qwen2.5-VL-7B 作为初步验证，后续可升级到 72B 版本

**备选方案：GPT-4o API**

如果网络条件允许、API 成本在预算内，GPT-4o 的可靠性更高，适合快速验证论文管线。

### 第二期（安全推理阶段）：GPT-4o 或 Claude 4 Sonnet

安全风险推理对场景理解和逻辑推理要求更高，闭源顶级模型（GPT-4o / Claude 4 Sonnet）表现更可靠。此时 VLM 已不再是核心 pipeline 的效率瓶颈。

---

## 4. 部署方案

### 4.1 统一推理接口

```python
# GMRobot/vlm/client.py
class VLMClient(ABC):
    @abstractmethod
    def analyze_scene(self, image: np.ndarray, prompt: str) -> dict:
        """场景分析 + grounding 关键词生成"""
        pass

    @abstractmethod
    def predict_risk(self, image: np.ndarray, context: dict) -> dict:
        """风险预测"""
        pass
```

### 4.2 后端实现

```python
# GMRobot/vlm/backends/qwen_vl.py
class QwenVLBackend(VLMClient):
    def __init__(self, model_name="Qwen/Qwen2.5-VL-7B-Instruct"):
        # 4-bit 量化加载
        ...

    def analyze_scene(self, image, prompt):
        # Qwen2.5-VL 推理
        ...

# GMRobot/vlm/backends/openai_api.py
class OpenAIBackend(VLMClient):
    def __init__(self, api_key, model="gpt-4o"):
        ...

    def analyze_scene(self, image, prompt):
        # GPT-4o API 调用
        ...
```

### 4.3 同机部署注意

```
┌─────────────────────────────────┐
│     RTX 4090 (24 GB)           │
│  ┌──────────┐ ┌──────────────┐  │
│  │ Isaac Sim│ │ Qwen2.5-VL  │  │
│  │ 8-12 GB  │ │ 4-bit 8 GB  │  │
│  └──────────┘ └──────────────┘  │
│         ≈ 16-20 GB             │
└─────────────────────────────────┘
```

24 GB 勉强够用。如果显存不足：
1. VLM 用 CPU offloading 降低推理速度换取显存
2. 将 VLM 分到第二张卡或另一台机器
3. 降低 `--num_envs` 减少 Sim 显存占用

---

## 5. 待确认的问题

| # | 问题 | 需要做什么 |
|---|------|---------|
| 1 | gpufree 服务器是否能访问 OpenAI API？ | 测试 `curl https://api.openai.com` |
| 2 | Qwen2.5-VL-7B 4-bit 能否在 4090 + Sim 同进程运行？ | 需实际测试显存占用 |
| 3 | VLM 推理频率多少合适？（论文没指定） | 建议每 epi 1-2 次，根据场景复杂度调整 |
| 4 | 是否需要支持 CPU fallback？ | 如果显存不够，推理速度会显著下降 |

---

## 6. 参考

- [Qwen2.5-VL GitHub](https://github.com/QwenLM/Qwen2.5-VL)
- [Qwen2.5-VL-7B-Instruct (HuggingFace)](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)
- [GPT-4o API](https://platform.openai.com/docs/models/gpt-4o)
- [GM-SafePick_VLM替换状态机技术方案（归档）](./GM-SafePick_VLM替换状态机技术方案.md)
- [GM-SafePick_添加相机技术文档.md](../../GM-SafePick_添加相机技术文档.md)
