# GM-SafePick：远程运行指南

本文说明如何在远程 GPU 服务器上运行 GM-SafePick 演示，包括：

- **无界面（headless）**：SSH 远程跑仿真（推荐）
- **带界面**：VNC 远程查看 Isaac Sim 3D 画面

适用于 gpufree 容器、云 GPU 服务器等无本地显示器的场景。

---

## 1. 环境前提

| 项目 | 要求 |
|------|------|
| GPU | NVIDIA GPU + 驱动（本机示例：RTX 4090） |
| 系统 | Ubuntu 22.04，GLIBC ≥ 2.35 |
| 磁盘 | 建议 ≥ 50GB 可用（Isaac Sim + 缓存） |
| 网络 | 首次运行需访问 Omniverse 下载资产 |

### 本机已配置路径（gpufree 示例）

| 路径 | 说明 |
|------|------|
| `/root/GMRobot` | 项目仓库 |
| `/root/gpufree-data/IsaacLab` | Isaac Lab 源码 |
| `/root/gpufree-data/conda/envs/env_isaaclab` | conda 环境 |
| `/root/activate_isaaclab.sh` | 一键激活脚本 |
| `/root/gpufree-data/isaac_env.sh` | 缓存与环境变量 |

若在其他机器部署，请按 [Isaac Lab pip 安装文档](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html) 安装后，将下文路径替换为实际路径。

---

## 2. 激活环境

每次运行前先执行：

```bash
source /root/activate_isaaclab.sh
```

等价于：

```bash
source /root/gpufree-data/isaac_env.sh
source /opt/conda/etc/profile.d/conda.sh
conda activate /root/gpufree-data/conda/envs/env_isaaclab
export TERM=xterm
cd /root/GMRobot
```

### 验证安装

```bash
source /root/activate_isaaclab.sh
python scripts/list_envs.py
```

应能看到 `Template-Gmrobot-v0` 等注册任务。

---

## 3. 远程无界面运行（headless，推荐）

通过 SSH 登录服务器后直接运行，无需显示器。

### 3.1 前台运行

```bash
source /root/activate_isaaclab.sh
python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras
```

### 3.2 后台运行（断开 SSH 仍继续）

```bash
source /root/activate_isaaclab.sh
nohup python scripts/gm_state_machine_agent.py --task=gm --headless --enable_cameras \
  > /root/gpufree-data/demo.log 2>&1 &

echo $! > /root/gpufree-data/demo.pid
```

查看日志：

```bash
tail -f /root/gpufree-data/demo.log
```

查看进程：

```bash
ps -fp $(cat /root/gpufree-data/demo.pid)
```

停止任务：

```bash
kill $(cat /root/gpufree-data/demo.pid)
```

### 3.3 缩短任务做连通性测试

完整演示需搬运 20 个零件，耗时较长。可临时修改 `scripts/gm_state_machine_agent.py` 中的 `DEFAULT_USER_COMMANDS`，仅保留 1 条命令做快速验证：

```python
DEFAULT_USER_COMMANDS = [
    {"pick": "A@1", "place": "B@1"},
]
```

### 3.4 并行环境

```bash
python scripts/gm_state_machine_agent.py --task=gm --headless --num_envs=16
```

---

## 4. 远程带界面运行（VNC 看 3D 画面）

headless 适合批量跑实验；若需要**远程观看仿真画面**，使用 VNC 或远程桌面。

### 4.1 安装 VNC 服务（Ubuntu 示例）

```bash
apt-get update
apt-get install -y tigervnc-standalone-server tigervnc-common dbus-x11

# 首次设置 VNC 密码（8 位以内）
vncpasswd
```

### 4.2 启动 VNC + 虚拟桌面

```bash
# 分辨率可按需调整
vncserver :1 -geometry 1920x1080 -depth 24
```

### 4.3 本机连接 VNC

1. 确保云平台/防火墙放行 VNC 端口（`:1` 对应 **5901**）
2. 用 VNC 客户端连接：`服务器IP:5901`
3. 在 VNC 桌面内打开终端，执行：

```bash
source /root/activate_isaaclab.sh
python scripts/gm_state_machine_agent.py --task=gm
```

**注意**：不要加 `--headless`，否则会无窗口。

### 4.4 关闭 VNC

```bash
vncserver -kill :1
```

### 4.5 其他远程看图方式

| 方式 | 说明 |
|------|------|
| 云平台 Web 桌面 | 部分 GPU 平台自带浏览器远程桌面，直接在内置终端运行即可 |
| SSH X11 转发 | `ssh -X user@host`（3D 仿真通常很慢，不推荐） |
| Isaac Sim WebRTC | 需额外配置 Omniverse 直播，适合高级用户 |

---

## 5. 从本地电脑 SSH 到服务器的完整流程

```bash
# 1. 本地终端连接
ssh root@<服务器IP>

# 2. 激活环境
source /root/activate_isaaclab.sh

# 3. 无界面运行
python scripts/gm_state_machine_agent.py --task=gm --headless

# 或后台运行
nohup python scripts/gm_state_machine_agent.py --task=gm --headless \
  > /root/gpufree-data/demo.log 2>&1 &
tail -f /root/gpufree-data/demo.log
```

---

## 6. 资产与首次运行

- **首次运行**会从 Omniverse 下载 Nucleus 资产（如 `SeattleLabTable`），可能需 10–30 分钟，属正常现象。
- **当前部署**（`/root/GMRobot`，主分支最新提交）：机器人、容器、隔板、零件均从**本地 USD** 加载；仅工作台从 Nucleus 在线缓存：

| 资产 | 来源 | 路径 |
|------|------|------|
| UR10e + 夹爪 | 本地 | `assets/ur10e_2f/ur10e_gripper.usd` |
| 容器 | 本地 | `assets/container.usd`（约 21 MB） |
| 隔板网格 | 本地 | `assets/container/GM_Container_Slim_Divider_Sim.usd` |
| 零件 | 本地 | `assets/part/part_5000.usd` |
| 工作台 | Nucleus | `SeattleLabTable/table_instanceable.usd` |

- **GitHub 克隆包**不含上述 `.usd`（`.gitignore` 排除）；完整资产须单独保留在本地 `assets/`。
- **历史占位方案**（无完整 USD 时）：曾用官方 `UR10e_ROBOTIQ_2F_85_CFG` 与 Omniverse `box.usd` / `dex_cube` 占位；**当前 canonical 目录已不再使用**。

资产路径以本节表格为准；克隆后须恢复本地 `assets/` 方可复现场景。

---

## 7. 常见问题

### Q1：找不到 USD 文件

确认资产路径正确，或首次运行等待 Omniverse 缓存下载完成。检查日志中是否有 `FileNotFoundError`。

### Q2：headless 长时间运行后崩溃（Mutex 断言）

Isaac Sim 5.1 headless 长时间运行偶发 `carb.tasking Mutex` 错误。可尝试：

- 缩短 `DEFAULT_USER_COMMANDS` 任务数量
- 使用 VNC 带界面模式运行
- 减少 `--num_envs`

### Q3：`No module named 'isaacsim'`

```bash
source /root/activate_isaaclab.sh
python -c "import isaacsim; print('ok')"
```

若失败，需重新安装 Isaac Sim pip 包（见 Isaac Lab 安装文档）。

### Q4：GPU 不可用

```bash
nvidia-smi
```

确认驱动与 GPU 在容器内可见。

### Q5：私有仓库 git pull 失败

使用 `/root/.github_token` 中的 token（**勿提交到 git**）：

```bash
source /root/.github_token
git pull "https://x-access-token:${GITHUB_TOKEN}@${GITHUB_REMOTE_URL#https://}" "${GITHUB_BRANCH}"
```

### Q6：Layer 3 VLM / 感知联调（SSH 隧道）

VLM（`:18080`）与感知（`:18082`）隧道、凭据、`--enable_vlm` / `--enable_perception` 烟测命令的**唯一权威说明**见 [AI 服务器部署 §0–§0.5 / §7](./GM-SafePick_AI服务器部署.md#0-本地凭据文件-rootgithub_tokenagent-必读)（含双隧道示例与 500 步 VLM 回归命令）。

本指南 §1–§3 仅覆盖 Isaac Sim headless 运行；**勿**在此重复维护隧道细节。

---

## 8. 命令速查

```bash
# 激活
source /root/activate_isaaclab.sh

# 验证环境
python scripts/list_envs.py

# headless 演示
python scripts/gm_state_machine_agent.py --task=gm --headless

# 带界面演示（需 VNC/桌面）
python scripts/gm_state_machine_agent.py --task=gm

# 后台 + 日志
nohup python scripts/gm_state_machine_agent.py --task=gm --headless > /root/gpufree-data/demo.log 2>&1 &
tail -f /root/gpufree-data/demo.log
```

---

## 9. 相关文档

| 文档 | 说明 |
|:-----|:-----|
| [GM-SafePick_项目进展与遗留问题.md](./GM-SafePick_项目进展与遗留问题.md) | **跨层进度看板**（唯一 SSOT） |
| [GM-SafePick_架构总览.md](./GM-SafePick_架构总览.md) | 三层架构与路标 |
| [GM-SafePick_AI服务器部署.md](./GM-SafePick_AI服务器部署.md) | VLM/感知 SSH 隧道与 gm-ai-server |
| [README.md](../../../README.md) | 平台概述与 Quick Start |
| [Isaac Lab 安装文档](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html) | 官方安装 |
