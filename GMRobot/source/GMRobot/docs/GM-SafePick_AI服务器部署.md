# GM-SafePick AI 专用服务器部署

> **日期**：2026-06-18  
> **关联 ADR**：[Phase 3.5 Motion Replan 契约](./adr/GM-SafePick_Phase3.5_MotionReplan契约.md) §10.6  
> **拓扑**：Isaac 本地（Sim）+ **gm-ai-server**（VLM 推理）

---

## 0. 本地凭据文件 `/root/.github_token`（Agent 必读）

> **路径**：`/root/.github_token`（Isaac gpufree 节点 **仓库外**，`chmod 600`）  
> **禁止**：不得 `git add`、不得写入本仓库任何 Markdown/YAML/脚本。

### 0.1 文件用途（双用途）

| 区块 | 变量 / 内容 | 用途 |
|:-----|:------------|:-----|
| **GitHub 私有仓** | `GITHUB_TOKEN`、`GITHUB_USER`、`GITHUB_REPO`、`GITHUB_REMOTE_URL`、`GITHUB_LOCAL_PATH` 等 | `git pull` / `git push` 至 `OVERLORD799/gmrobot`（经 `gh-proxy.org` 镜像） |
| **gm-ai-server SSH** | 文件**末尾两行**：`ssh -p <port> root@<host>` + **下一行**为 SSH 密码 | 登录 AI 专用服务器、建立 VLM 端口转发 |

后续 Agent **应先** `source /root/.github_token` 加载 GitHub 变量；SSH 密码**不在** shell 变量中，需从文件末尾两行读取（或交互输入），**勿**在对话/提交中粘贴明文。

### 0.2 Agent 工作流：Git 同步

```bash
source /root/.github_token
cd "${GITHUB_LOCAL_PATH}"
git pull "https://x-access-token:${GITHUB_TOKEN}@${GITHUB_REMOTE_URL#https://}" "${GITHUB_BRANCH}"
```

完整一键更新见文件内注释；亦可执行 `bash /root/apply_github_auth.sh`（若存在）。

### 0.3 Agent 工作流：VLM / 感知 SSH 隧道（Sim → gm-ai-server）

**拓扑**：VLM FastAPI 监听 AI 服务器 **本机** `127.0.0.1:8080`；感知服务 **本机** `127.0.0.1:8082`。Isaac 节点经 SSH 转发至本地 **`18080`** / **`18082`**。

```bash
# 1) 确认远端服务常驻
#    curl -s http://127.0.0.1:8080/health   # VLM 期望 {"status":"ok",...}
#    curl -s http://127.0.0.1:8082/health   # 感知期望 status=ok 或 warming

# 2) 在 Isaac 节点建立隧道（密码见 /root/.github_token 末尾，勿提交）
#    交互式（VLM + 感知双转发）：
ssh -N \
  -L 18080:127.0.0.1:8080 \
  -L 18082:127.0.0.1:8082 \
  -p <PORT> root@<HOST>

# 3) 本地验证
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18082/health
```

Sim 侧 [`configs/vlm_client.yaml`](../../../../configs/vlm_client.yaml)：`base_url: http://127.0.0.1:18080`。  
Sim 侧 [`configs/perception_client.yaml`](../../../../configs/perception_client.yaml)：`base_url: http://127.0.0.1:18082`。

### 0.4 VLM 短测命令（不启 Isaac）

```bash
curl -s http://127.0.0.1:18080/health | python3 -m json.tool
# 期望: status=ok, model_id 含 Qwen2.5-VL
```

### 0.5 S8 Isaac 500 步联调（`vlm_*` CSV 非空验证）

```bash
source /root/activate_isaaclab.sh
cd /root/GMRobot
scripts/isaac_gpu_lock.sh python scripts/gm_state_machine_agent.py \
  --task=gm --headless --enable_cameras --enable_safety \
  --max_steps=500 --progress_interval=100 --enable_vlm
```

完成后检查 `output/safety_logs/<run_id>/episode_0000.csv`：`vlm_risk_class`、`vlm_confidence`、`vlm_suggested_action`、`model_id` 在 VLM 推理步（约每 100 步）应非空；非推理步为前向填充。

---

## 1. 服务器规格（已探测）

| 项 | 值 |
|:---|:---|
| SSH | `ssh gm-ai-server` 或 `ssh -p 30481 root@120.209.70.195` |
| 凭证 | `/root/.github_token` 文件末尾（**禁止提交 git**） |
| GPU | NVIDIA **L40S 48 GB** |
| 驱动 | **580.126.09** |
| OS | Ubuntu 22.04（容器 `gpufree-container`） |
| RAM | **1 TB** |
| 数据盘 | `/root/gpufree-data`（49 GB，模型与 conda env） |

---

## 2. 环境路径

| 路径 | 用途 |
|:-----|:-----|
| `/root/gpufree-data/conda-envs/vlm` | Conda 环境，Python **3.11** |
| `/root/gpufree-data/huggingface` | HF 模型缓存（`HF_HOME`） |
| `/root/gpufree-data/vlm-service/` | 服务脚本、`start.sh`、日志 |

---

## 3. 安装步骤（Phase 3a — Qwen MVP）

```bash
# 1) SSH 登录
ssh gm-ai-server

# 2) 创建 conda 环境
source /opt/conda/etc/profile.d/conda.sh
conda create -y -p /root/gpufree-data/conda-envs/vlm python=3.11 pip
conda activate /root/gpufree-data/conda-envs/vlm

# 3) PyTorch + CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 4) VLM 依赖
pip install transformers accelerate qwen-vl-utils pillow bitsandbytes \
  fastapi uvicorn[standard] httpx

# 5) HF 镜像（服务器直连 huggingface.co 偶发不可达）
export HF_HOME=/root/gpufree-data/huggingface
export HF_ENDPOINT=https://hf-mirror.com

# 6) Smoke test
python /root/gpufree-data/vlm-service/smoke_test.py
```

**量化说明**：MVP 使用 **bitsandbytes 4-bit NF4**（显存 ~8 GB，推理 ~1 s）。ADR 目标 AWQ；后续可切换 `autoawq` 或 vLLM AWQ 量化权重，接口不变。

---

## 4. 服务启动与常驻（VLM 可并行、SSH 断开不影响）

> **2026-06-22**：VLM 已纳入 gpufree 容器内 **supervisord** 托管；`systemd` 在容器内为 `offline`，**未使用**。

### 4.1 拓扑与路径

| 项 | 值 |
|:---|:---|
| 主程序 | `/root/gpufree-data/vlm-service/app.py`（Qwen2.5-VL FastAPI） |
| 启动脚本 | `/root/gpufree-data/vlm-service/start.sh`（conda env + `HF_HOME` / `HF_ENDPOINT`） |
| 监听 | `0.0.0.0:8080`（Sim 侧经 SSH 隧道访问 `127.0.0.1:8080`） |
| supervisord 配置 | `/.gpufree/vlm-service.conf` → 程序名 **`vlm-service`** |
| 主配置 | `/opt/supervisord.yaml`（`tini` 拉起 `/data/supervisord`） |
| 备用钩子 | `/root/start.sh`（仅当环境变量 `need_service=1` 时由 `startup_service` 执行） |

容器 **重启后自动拉起** `vlm-service`（`autostart=true`，`autorestart=true`）。进程崩溃时 supervisord 会重试启动；模型加载约 **15–90 s** 后 `/health` 才返回 `ok`。

### 4.2 启停 / 重启（在 gm-ai-server 上）

```bash
# 推荐：supervisord 子命令（配置路径固定）
/data/supervisord ctl -c /opt/supervisord.yaml start vlm-service
/data/supervisord ctl -c /opt/supervisord.yaml stop vlm-service

# 部分镜像上 restart 可能提示 not restarted；可 stop 后 start，或确认仅有一个 app.py：
pgrep -af "python app.py"
# 若端口被孤儿进程占用，结束非 supervisord 子进程（PPID 应为 supervisord PID）后再 start
```

**勿**对 supervisord 主进程 `kill`（会连带 **sshd** 短暂不可用）。仅操作 `vlm-service` 程序。

**手工兜底**（调试，非首选）：

```bash
nohup /root/gpufree-data/vlm-service/start.sh >> /root/gpufree-data/vlm-service/server.log 2>&1 &
```

日志：`/root/gpufree-data/vlm-service/supervisor.out.log`、`supervisor.err.log`、`server.log`。

### 4.3 Agent 健康检查

| 位置 | 命令 | 期望 |
|:-----|:-----|:-----|
| **远端本机** | `curl -s http://127.0.0.1:8080/health` | `{"status":"ok","model_id":"Qwen/Qwen2.5-VL-7B-Instruct",...}` |
| **Isaac 节点（隧道）** | 先建隧道（见 §0.3 / §6），再 `curl -s http://127.0.0.1:18080/health` | 同上 |
| 格式化 | `curl -s http://127.0.0.1:18080/health \| python3 -m json.tool` | `status` 为 `ok` |

隧道示例（密码见 `/root/.github_token` 末尾，**勿提交**）：

```bash
sshpass -e ssh -f -N -L 18080:127.0.0.1:8080 -p <PORT> root@<HOST>
```

### 4.4 HTTP API

| 端点 | 方法 | 说明 |
|:-----|:-----|:-----|
| `http://127.0.0.1:8080/health`（远端） | GET | 健康检查 |
| `http://127.0.0.1:18080/health`（Sim 经隧道） | GET | 同上 |
| `/analyze` | POST | VLM 推理（JSON） |

**请求示例**（在 gm-ai-server 上）：

```bash
curl -X POST http://127.0.0.1:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Is a human hand blocking the bin?","image_path":"/root/gpufree-data/vlm-service/sample.jpg"}'
```

**响应字段**（与 Layer 3 / `vlm_*` 列对齐）：

```json
{
  "model_id": "Qwen2.5-VL-7B-Instruct-4bit-nf4",
  "latency_ms": 850.3,
  "text": "...",
  "vlm_risk_type": "none",
  "vlm_severity": "low",
  "vlm_suggested_action": "continue",
  "vlm_confidence": 0.5
}
```

Sim 侧 [`configs/vlm_client.yaml`](../../../../configs/vlm_client.yaml)：`base_url: http://127.0.0.1:18080`（经隧道，勿依赖外网直连 8080）。

---

## 5. 2026-06-18 安装状态

| 步骤 | 状态 |
|:-----|:----:|
| nvidia-smi / OS / 磁盘验证 | ✅ |
| Conda env Python 3.11 | ✅ |
| PyTorch 2.6.0+cu124 | ✅ |
| Qwen2.5-VL-7B-Instruct 4-bit 加载 | ✅ |
| Smoke test（单图推理 ~1.25 s） | ✅ |
| FastAPI `/analyze` 真推理（~850 ms） | ✅ |
| supervisord 常驻 `vlm-service`（`/.gpufree/vlm-service.conf`） | ✅ 2026-06-22 |
| GDINO + SAM2（S9 MVP） | ✅ 2026-06-22：`perception-service` supervisord 常驻（`/.gpufree/perception-service.conf`） |

**已知限制**：

- 首次 HF 下载需 `HF_ENDPOINT=https://hf-mirror.com`；直连 huggingface.co 曾报 `Network unreachable`
- 服务启动加载权重约 **15–30 s**（缓存后）；首次下载约 **7 min**
- 8080 端口外网可达性取决于 gpufree 防火墙；内网 Sim 节点需确认路由

---

## 6. Isaac 节点 SSH 隧道（Sim → VLM）

VLM 仅监听 AI 服务器本机 `127.0.0.1:8080`；Isaac gpufree 节点通过 SSH 端口转发访问。

```bash
# 在 Isaac 机器上执行（后台 -f -N）
ssh -f -N -L 18080:127.0.0.1:8080 -p 30481 root@120.209.70.195

# 验证（应返回 {"status":"ok",...}）
curl http://127.0.0.1:18080/health
```

Sim 侧 [`configs/vlm_client.yaml`](../../../../configs/vlm_client.yaml) 使用 `base_url: http://127.0.0.1:18080`。凭证见 `/root/.github_token` 末尾（勿提交 git）。

---

## 7. Phase 3b / S9：Grounding DINO + SAM2（感知服务）

> **日期**：2026-06-22  
> **对齐**：[Layer 3 感知链](./GM-SafePick_Layer3_VLM推理增强层.md) Stage 2（GDINO 开放词汇检测 → SAM2 掩码）  
> **与 VLM 关系**：独立进程、**同 GPU（L40S）**；VLM 仍占 `:8080`，感知占 **`127.0.0.1:8082`**（Sim 经 SSH 转发建议 **`18082`**）

### 7.1 同机显存与并行策略

| 组件 | 端口 | 常驻显存（实测 2026-06-22） | 说明 |
|:-----|:-----|:----------------------------|:-----|
| Qwen2.5-VL 7B 4-bit | `8080` | ~6.5 GB | supervisord `vlm-service` |
| GDINO-tiny + SAM2.1 hiera-tiny | `8082` | +~2.7 GB（加载后合计 **~9.3 GB**） | 懒加载；余量 **~36 GB** |
| 推理延迟 | — | 首帧 `/ground` ~7.5 s；SAM2 单框 ~150 ms | GDINO 受 HF 镜像限速影响首载更慢 |

**结论**：L40S 48 GB 上 **Qwen + GDINO + SAM2 可同时常驻**；勿与 Isaac Sim 争用此卡（Sim 在本地节点）。

### 7.2 路径与 Conda

| 路径 | 用途 |
|:-----|:-----|
| `/root/gpufree-data/perception-service/app.py` | FastAPI：`/health`、`/ground` |
| `/root/gpufree-data/perception-service/smoke_test.py` | 离线烟测（无 HTTP） |
| `/root/gpufree-data/perception-service/start.sh` | conda `vlm` env + `HF_HOME` / `HF_ENDPOINT` |
| `/.gpufree/perception-service.conf` | supervisord 程序名 **`perception-service`** |
| `/root/gpufree-data/perception-service/checkpoints/sam2.1_hiera_tiny.pt` | SAM2.1 tiny 权重（~149 MB） |
| HF 缓存 | `IDEA-Research/grounding-dino-tiny` 在 `HF_HOME` |

**依赖**（已装入 `/root/gpufree-data/conda-envs/vlm`）：`sam2`、`opencv-python-headless`、`supervision`；GDINO 走 **transformers**（已有）。

### 7.3 安装（已完成步骤 + 复现）

```bash
# SSH 登录 gm-ai-server 后
source /opt/conda/etc/profile.d/conda.sh
conda activate /root/gpufree-data/conda-envs/vlm
export HF_HOME=/root/gpufree-data/huggingface
export HF_ENDPOINT=https://hf-mirror.com

pip install opencv-python-headless supervision sam2

python - <<'PY'
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id="facebook/sam2.1-hiera-tiny",
    filename="sam2.1_hiera_tiny.pt",
    local_dir="/root/gpufree-data/perception-service/checkpoints",
)
PY

/root/gpufree-data/perception-service/smoke_test.py   # 期望末尾 smoke_ok
```

### 7.4 启停 / 常驻（supervisord，与 VLM 并行）

| 项 | 值 |
|:---|:---|
| 启动脚本 | `/root/gpufree-data/perception-service/start.sh` |
| 监听 | **`127.0.0.1:8082`**（Sim 经 SSH 隧道建议 `18082`） |
| supervisord 配置 | `/.gpufree/perception-service.conf` → 程序名 **`perception-service`** |
| 主配置 | `/opt/supervisord.yaml`（与 §4 相同） |

容器 **重启后** `autostart=true` / `autorestart=true` 与 `vlm-service` 一并拉起。首次写入 `/.gpufree/` 新 program 后，若进程未出现，**重启 gpufree 容器**（或等待下次容器重建）以让 supervisord 读入配置；勿对 supervisord 主进程 `kill`。

```bash
# 推荐：supervisord 子命令（配置路径固定，与 §4.2 相同）
/data/supervisord ctl -c /opt/supervisord.yaml start perception-service
/data/supervisord ctl -c /opt/supervisord.yaml stop perception-service

# 与 VLM 同检（远端本机）
curl -s http://127.0.0.1:8080/health && curl -s http://127.0.0.1:8082/health

# 若端口被孤儿进程占用，结束非 supervisord 子进程后再 start
pgrep -af "gpufree-data/perception-service"
```

**手工兜底**（调试，非首选）：

```bash
nohup /root/gpufree-data/perception-service/start.sh \
  >> /root/gpufree-data/perception-service/supervisor.out.log 2>> /root/gpufree-data/perception-service/supervisor.err.log &
```

日志：`/root/gpufree-data/perception-service/supervisor.out.log`、`supervisor.err.log`、`server.log`。

### 7.5 Agent 健康检查

| 位置 | 命令 | 期望 |
|:-----|:-----|:-----|
| **远端本机** | `curl -s http://127.0.0.1:8082/health` | `status` 为 `ok` 或首次 `warming`（未调 `/ground`） |
| **远端烟测** | `/root/gpufree-data/perception-service/smoke_test.py` | 输出 `smoke_ok` |
| **Isaac 节点（隧道）** | `ssh -L 18082:127.0.0.1:8082 ...` 后 `curl -s http://127.0.0.1:18082/health` | 同 VLM 隧道模式（§0.3） |
| **与 VLM 同检** | `curl -s http://127.0.0.1:8080/health && curl -s http://127.0.0.1:8082/health` | 两者均 `ok` |

### 7.6 HTTP API（GMRobot 客户端草案）

| 端点 | 方法 | 说明 |
|:-----|:-----|:-----|
| `/health` | GET | `models_loaded`、`gdino_model_id`、`sam2_checkpoint` |
| `/ground` | POST | 文本提示 + 图像 → 检测框 + 可选 SAM2 掩码面积 |
| `/track` | POST | SAM2 视频时序追踪（`action=init` 建会话 / `action=step` 传播） |

**`/track` 请求**（Isaac shadow；与 `/ground` 同 `base_url`）：

```bash
# init — GDINO 文本或 box_xyxy 种子
curl -s -X POST http://127.0.0.1:8082/track \
  -H "Content-Type: application/json" \
  -d '{
    "action": "init",
    "frame_index": 0,
    "image_b64": "<PNG base64>",
    "init": {
      "target_label": "hand",
      "text_prompt": "gloved hand . robot gripper",
      "box_threshold": 0.2,
      "re_detect_every_n": 100
    },
    "meta": {"step": 0}
  }'

# step — 携带 session_id 与下一帧
curl -s -X POST http://127.0.0.1:8082/track \
  -H "Content-Type: application/json" \
  -d '{
    "action": "step",
    "session_id": "<uuid>",
    "frame_index": 1,
    "image_b64": "<PNG base64>",
    "meta": {"step": 1}
  }'
```

**`/track` 响应字段**（S13 P1 shadow CSV 映射）：

```json
{
  "session_id": "…",
  "frame_index": 1,
  "re_detected": false,
  "latency_ms": 42.0,
  "tracks": [
    {
      "track_id": 0,
      "label": "hand",
      "box_xyxy": [12.3, 4.5, 640.0, 480.0],
      "center_xy": [326.1, 242.2],
      "velocity_xy_px_s": [18.5, -6.2],
      "speed_px_s": 19.5,
      "direction_deg": -18.4,
      "mask_area": 304789,
      "sam2_score": 0.99
    }
  ]
}
```

Sim 侧 agent：`--enable_perception --enable_perception_track`；CSV 新增 `perception_track_*` 五列（center/speed/direction/label，与既有 `perception_*` 五列前向填充）。客户端：`PerceptionClient.track_frame()`、`PerceptionTrackSession`；烟测 `python scripts/test_perception_client.py --track`。

**请求示例**（gm-ai-server）：

```bash
curl -s -X POST http://127.0.0.1:8082/ground \
  -H "Content-Type: application/json" \
  -d '{
    "text_prompt": "gloved hand . robot gripper",
    "image_path": "/root/gpufree-data/vlm-service/sample.jpg",
    "box_threshold": 0.2,
    "run_sam2": true
  }'
```

**响应字段**（与 Layer 3 `combined_query` 对接）：

```json
{
  "gdino_model_id": "IDEA-Research/grounding-dino-tiny",
  "sam2_checkpoint": "sam2.1_hiera_tiny.pt",
  "latency_ms": 7560.9,
  "detections": [
    {
      "label": "hand",
      "score": 0.21,
      "box_xyxy": [12.3, 4.5, 640.0, 480.0],
      "mask_area": 304789,
      "sam2_score": 0.99
    }
  ]
}
```

Sim 侧 [`configs/perception_client.yaml`](../../../../configs/perception_client.yaml)：`base_url: http://127.0.0.1:18082`（与 `vlm_client.yaml` 并列）。客户端实现：[`GMRobot/perception/client.py`](../GMRobot/perception/client.py)；Sim 烟测 `python scripts/test_perception_client.py`。

### 7.7 已知限制与后续

- **HF 镜像 429**：首载 GDINO 可能等待重试；权重缓存后稳定。
- **supervisord 热加载**：gpufree 镜像上 `ctl reload` 通常**不会**为新增 `/.gpufree/*.conf` 拉起进程；配置已落盘，**容器重启**后 autostart 生效。`ctl start/stop` 回显 `not started` 时，以 `pgrep` / `curl` 为准。
- **模型规格**：当前为 **tiny** 栈（烟测）；生产可换 `grounding-dino-base` + `sam2.1_hiera_small` 并评估延迟。
- **视频追踪**：服务端 `/track` 实现已就位（[`perception_track_endpoint.py`](./perception_track_endpoint.py) — 2026-06-27）；待部署至 gm-ai-server（见 §7.8）；客户端与 CSV 列 **2026-06-22 已就绪**。

### 7.8 `/track` 服务端部署步骤（W5）

```bash
# 1) Copy 实现文件到 gm-ai-server
scp -P 30481 source/GMRobot/docs/perception_track_endpoint.py \
  root@120.209.70.195:/root/gpufree-data/perception-service/

# 2) 在 gm-ai-server 上编辑 app.py，在 create_app() 末尾添加：
#    from perception_track_endpoint import register_track_endpoint
#    register_track_endpoint(app, gdino_model, gdino_processor, sam2_predictor)

# 3) 重启 perception-service
/data/supervisord ctl -c /opt/supervisord.yaml stop perception-service
/data/supervisord ctl -c /opt/supervisord.yaml start perception-service

# 4) 验证（远端本机）
curl -s -X POST http://127.0.0.1:8082/track \
  -H "Content-Type: application/json" \
  -d '{"action":"init","frame_index":0,"image_b64":"<PNG>","init":{"target_label":"hand"}}'
```

---

## 8. Phase 3b 扩展（AWQ 等）

| 组件 | 说明 |
|:-----|:-----|
| AWQ 权重 | 可选替换 Qwen bitsandbytes，降低 VLM 延迟 |
| 更大 GDINO/SAM2 | 精度 ↑、显存与延迟 ↑；见 §7.7 |


---

*凭证与密码不得写入本仓库；SSH 别名见本地 `~/.ssh/config`。*
