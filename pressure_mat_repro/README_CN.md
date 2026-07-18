# 压力垫触觉 → 质心速度 — 复现包

Unitree **G1（29自由度）**人形机器人在 Isaac Lab 中的模拟**触觉压力垫**上行走。每个触觉单元（taxel）的接触力图像被输入到一个 CNN+GRU 网络中，该网络预测机器人的质心速度 `(vx, vy, vz)`。本包可让你复现**演示**（行走 + 实时速度预测视频）以及基于触觉数据**训练/评估**速度网络。

Isaac Lab 任务是**完全自包含的**：仅依赖*标准* Isaac Lab 安装加上本包中的文件。**无需对 Isaac Lab 核心或资产库进行任何修改。**

---

## 1. 我们使用的版本

| 组件 | 版本 |
|---|---|
| Isaac Sim | **4.2.0** |
| Isaac Lab | **1.3.0**（命名空间 `omni.isaac.lab.*`） |
| Python（仿真） | 3.10 |
| Python（速度训练） | 3.6 |
| PyTorch（速度训练） | 1.6.0 + CUDA 10.2 |
| 使用的 GPU | NVIDIA RTX 2080 Ti（11 GB）— 1 块 GPU 足够 |

> 请先安装标准 Isaac Sim 4.2.0 + Isaac Lab 1.3.0，参照
> https://isaac-sim.github.io/IsaacLab/（v1.3.0 文档）。以下所有内容假定
> 你的 Isaac Lab 目录中 `./isaaclab.sh` 可以正常运行。

有**两个 Python 环境**：
- **Isaac Lab** 环境（Python 3.10）— 运行仿真、行走演示、数据采集和实时验证视频。通过 `./isaaclab.sh -p` 调用。
- **速度训练**环境（Python 3.6，torch 1.6）— 训练/评估 CNN+GRU 速度模型。只需要 `torch`、`numpy`、`progressbar2`。

---

## 2. 包内容

```
pressure_mat_repro/
├── README.md                      ← 本文件
├── MANIFEST.md                    ← 每个文件 + 放置位置 + 原因
├── isaac_lab_task/
│   └── pressure_mat_deploy/       ← 任务包（放入 Isaac Lab 中，见安装说明）
│       ├── __init__.py            ← 注册 PressureMat-Walk-G1-Deploy-v0（及 HiRes）
│       ├── deploy_env_cfg.py      ← 32×32 / 4 米垫子环境（演示任务）
│       ├── deploy_hires_env_cfg.py← 64×64 / 4 米垫子环境（消融实验）
│       ├── robot_cfg.py           ← G1 29 自由度行走机器人配置（内置）
│       ├── mdp/
│       │   ├── __init__.py
│       │   ├── observations.py    ← 触觉力图像 + 部署行走观测辅助
│       │   ├── terminations.py    ← 走出垫子的终止条件
│       │   └── walk_action.py     ← 12 自由度仅腿部动作项（内置）
│       └── data/
│           ├── g1_29dof_modified_new_91.usd   ← 机器人 USD（31 MB）
│           ├── tactile_mat_32x32_4m.usd        ← 32×32 垫子 USD
│           └── tactile_mat_64x64_4m.usd        ← 64×64 垫子 USD（高分辨率）
├── policy/
│   └── 0121_walk.pt               ← G1 行走策略（torchscript，1.9 MB）
├── scripts/                       ← 通过 ./isaaclab.sh -p 运行
│   ├── play_deploy_walk_policy.py ← 让机器人行走，可选仿真+触觉视频
│   ├── collect_tactile_motion_deploy.py ← 采集（触觉, 质心）数据集
│   ├── validate_tactile_hybrid.py ← 实时演示：仿真 + 真实 vs 预测速度
│   └── smoke_test.py              ← 快速自检（无需 tree 安装）
└── velocity_training/             ← CNN+GRU 训练/评估（Python 3.6 + torch 1.6）
    ├── velocity_temporal_model.py ← SequentialTactileHybridRegressor
    ├── velocity_train_seq.py      ← 训练器（32×32）
    ├── velocity_train_seq_64.py   ← 训练器（64×64 高分辨率）
    ├── velocity_train_seq_noisy.py← 训练器（带高斯触觉噪声）
    ├── velocity_dataLoader_*.py   ← 序列数据加载器（32/64/噪声 + 基础工具）
    ├── velocity_model_final.py    ← 掩码 MSE 损失辅助函数
    ├── ckpts/
    │   └── g1_walk_deploy_v1_seqhybrid_0.0001_seq_best.path.tar  ← 演示检查点
    └── ablation_ckpts/            ← 噪声 σ=5、σ=15 和 64×64 高分辨率检查点
```

---

## 3. 安装

### 3a. Isaac Lab 任务包
将任务文件夹复制到你的 Isaac Lab 目录的任务树中，然后在 `import omni.isaac.lab_tasks` 时它会自动注册：

```bash
ISAACLAB=/path/to/IsaacLab          # 你的标准 Isaac Lab 1.3.0 目录
REPRO=/path/to/pressure_mat_repro   # 本包

cp -r "$REPRO/isaac_lab_task/pressure_mat_deploy" \
      "$ISAACLAB/source/extensions/omni.isaac.lab_tasks/omni/isaac/lab_tasks/manager_based/"
```

这是仿真端的**唯一**安装步骤——不会触碰任何核心文件。
（机器人和垫子的 USD 文件随 `pressure_mat_deploy/data/` 一起携带，因此该包是可重定位的。）

快速检查导入是否正常 + 策略能否行走（不会修改你的文件树）：
```bash
cd "$ISAACLAB"
./isaaclab.sh -p "$REPRO/scripts/smoke_test.py" \
    --pkg_dir "$REPRO/isaac_lab_task" \
    --policy  "$REPRO/policy/0121_walk.pt" \
    --headless
# 预期：walker obs (1,588)、tactile (1,32,32)、策略行走、" [smoke] PASS"
```

### 3b. 速度训练环境（Python 3.6）
```bash
conda create -n vel python=3.6 -y && conda activate vel
pip install torch==1.6.0 numpy progressbar2
```

---

## 4. 复现演示

以下所有命令请在 Isaac Lab 根目录（`cd "$ISAACLAB"`）中运行。始终传入
`--policy "$REPRO/policy/0121_walk.pt"`（脚本默认指向其他路径）。

> **无头模式 vs 窗口模式：** 保留 `--headless` 以进行无 GUI 运行，仅写入 mp4（我们使用的方式）。**去掉 `--headless`** 可在 Isaac Sim GUI 窗口中实时观看。所有演示命令均使用 **`--num_envs 1`**（单个机器人）。

**(a) 让机器人行走 + 并排录制仿真视口 + 触觉热力图：**
```bash
./isaaclab.sh -p "$REPRO/scripts/play_deploy_walk_policy.py" \
    --task PressureMat-Walk-G1-Deploy-v0 \
    --num_envs 1 \
    --policy "$REPRO/policy/0121_walk.pt" \
    --cmd_seq "0.5,0,0;-0.4,0,0;0,0.3,0;0,-0.3,0;0,0,1.0;0,0,-1.0;0.3,0.3,0" \
    --steps_per_cmd 60 \
    --record_video "$REPRO/out" --side_by_side_tactile --headless
```
`--cmd_seq` 是一系列 `vx,vy,wz` 指令（单位：m/s、m/s、rad/s）；每条指令持续
`--steps_per_cmd` 个环境步数。指令范围：`vx∈[-0.8,0.8]`、`vy∈[-0.5,0.5]`、`wz∈[-1.57,1.57]`。

**(b) 实时速度预测演示（主打视频——左侧仿真，右侧真实 vs 预测速度）：**
```bash
./isaaclab.sh -p "$REPRO/scripts/validate_tactile_hybrid.py" \
    --task PressureMat-Walk-G1-Deploy-v0 \
    --num_envs 1 \
    --policy "$REPRO/policy/0121_walk.pt" \
    --ckpt  "$REPRO/velocity_training/ckpts/g1_walk_deploy_v1_seqhybrid_0.0001_seq_best.path.tar" \
    --num_steps 500 --record_video "$REPRO/out" --headless
# 打印实时 MAE；保存 out/validate_hybrid_<ts>.mp4（速度 MAE ≈ 0.08 m/s）
```

---

## 5. 采集数据 + 训练/评估速度网络

**(a) 采集合成（触觉, 质心）数据集**（40 个并行环境，10 Hz，intelligentCarpet 模式 = `log.p` + 每序列目录的帧 pickle 文件 `[tactile(R,C), None, keypoint(21,3)]`，质心位于关键点 0 和 8）：
```bash
./isaaclab.sh -p "$REPRO/scripts/collect_tactile_motion_deploy.py" \
    --task PressureMat-Walk-G1-Deploy-v0 \
    --policy "$REPRO/policy/0121_walk.pt" \
    --num_envs 40 --target_frames 60000 --tactile_out_size 0 \
    --out_dir /path/to/dataset --headless
```
> 若要基于**真实**垫子数据进行训练/评估，请按相同的模式组织数据
> （每帧 32×32 触觉数据，质心在关键点 0 和 8，`log.p` 列出序列起始索引），
> 然后将下方的 `--train_dir/--val_dir` 指向该数据。

**(b) 训练 CNN+GRU 速度模型**（Python 3.6 环境，在 `velocity_training/` 目录下）：
```bash
conda activate vel
cd "$REPRO/velocity_training"
python velocity_train_seq.py \
    --epoch 30 --batch_size 4 --num_workers 4 \
    --train_dir /path/to/dataset/ --val_dir /path/to/dataset/ \
    --exp my_run --fps_default 10 --smooth_radius 1 \
    --head_idx 0 --anchor_idx 8 --position_scale 1.0 --velocity_norm 1.0
# 最佳检查点 -> ./train/ckpts/my_run_0.0001_seq_best.path.tar
```
变体：`velocity_train_seq_64.py`（64×64 数据）、`velocity_train_seq_noisy.py --noise_sigma 5`（高斯触觉噪声增强，单位：牛顿）。

**(c) 评估** = 运行实时验证演示（§4b），将 `--ckpt` 指向你训练好的 `*_seq_best.path.tar`，对于 64×64 检查点可选 `--task PressureMat-Walk-G1-Deploy-HiRes-v0`。

---

## 6. 提供的检查点

| 文件 | 垫子分辨率 | 训练噪声 | 实时速度 MAE |
|---|---|---|---|
| `ckpts/...seqhybrid_0.0001_seq_best.path.tar` | 32×32 | 无 | **0.078 m/s** ← 演示 |
| `ablation_ckpts/...n5...` | 32×32 | σ=5 N | 0.082 m/s |
| `ablation_ckpts/...n15...` | 32×32 | σ=15 N | 0.132 m/s |
| `ablation_ckpts/...hires...` | 64×64 | 无 | 0.105 m/s |

模型 = `SequentialTactileHybridRegressor`（每帧 CNN 作用于 3 帧局部堆栈 → 因果 GRU 带 4 帧未来前瞻 → 每时间步 `(vx,vy,vz)`）。
`validate_tactile_hybrid.py` 内联重新定义了此类，因此评估无需导入 `velocity_training/`——只需一个检查点。

---

## 7. 注意事项/常见问题

- **垫子分辨率：** 4 米垫子上的 32×32 分辨率（≈12.9 cm 间距）是最佳平衡点。
  更精细的垫子（64×64）会导致行走噪声更大、单格力信噪比更低；
  `HiRes` 任务 + `...hires...` 检查点可复现该消融实验。
- **为什么机器人在垫子上行走顺畅：** 垫子 USD 内置了与地平面匹配的摩擦力（0.5/0.5 + 面片摩擦力）和高触觉单元质量；机器人脚部摩擦力通过重置事件设置为 0.8/0.6。这些已包含在提供的 USD/环境配置中——无需手动调整。
- **触觉图像** 是每个触觉单元的法向力（单位：牛顿），经过标定使得每只脚的图像总和等于该脚的净地面反作用力，然后经过 Pasternak 平滑处理（`coupling_length=0.01 m`）。
- 脚本可指向的两个额外任务：`PressureMat-Walk-G1-Deploy-v0`（32×32）和 `PressureMat-Walk-G1-Deploy-HiRes-v0`（64×64）。
