# AMO 算法调研与 GMDisturb 适用性评估

> 调研日期：2026-07-06
> 来源：https://github.com/OpenTeleVision/AMO (RSS 2025)

## 算法概要

AMO (Adaptive Motion Optimization) 是 UCSD 提出的 sim-to-real 强化学习框架，用于**超灵巧人形全身控制**。
发表于 RSS 2025/2026，作者 Jialong Li, Xuxin Cheng, Xiaolong Wang 等。

### 核心架构（4 层层次化系统）

```
┌─────────────────────────────────────────┐
│ 1. AMO Module (3-layer MLP, frozen)     │
│    上半身姿态 + 躯干命令 → 下半身参考   │
├─────────────────────────────────────────┤
│ 2. Teacher Lower Policy (PPO, IsaacGym) │
│    4096 并行环境，特权观测               │
├─────────────────────────────────────────┤
│ 3. Student Lower Policy (distilled)     │
│    本体感知 + 25 步历史，50Hz 部署       │
├─────────────────────────────────────────┤
│ 4. Upper Policy (teleop or vision)      │
│    VR 遥操作 或 双目视觉自主策略         │
└─────────────────────────────────────────┘
```

### 支持的平台

| 项目 | 状态 |
|------|------|
| Unitree G1 (29-DOF) | ✅ 唯一验证平台 |
| Unitree Dex3-1 手 (7-DOF×2) | ✅ 已验证 |
| Unitree H1 | ❌ 不支持 |
| Inspire 手 (5 指) | ❌ 未测试 |
| 其他人形 (Fourier, Tesla, Figure) | ❌ 不支持 |

### 控制接口

- **输入**：VR 头显（操作者头部姿态）+ VR 控制器（手部姿态）+ 键盘（辅助命令）
- **输出**：29-DOF 关节位置目标 @ 50Hz，PD 控制器执行
- **上肢控制**：IK + dex-retargeting（VR 手姿 → 机器人关节角）
- **下肢控制**：Student Policy（本体感知 → 腿部关节目标）
- **训练**：IsaacGym 4096 并行环境，需要完整 AMO Dataset 生成管线

### 依赖项

- NVIDIA IsaacGym (非 Isaac Sim)
- MuJoCo (运动学优化)
- AMASS MoCap 数据集 (上肢参考动作)
- VR 头显 + 控制器 (Apple Vision Pro / Meta Quest)

### 与 GMDisturb 的不兼容性

| GMDisturb 需求 | AMO 提供 | 匹配？ |
|---------------|---------|--------|
| 脚本化扰动（速度命令 + 手臂姿态） | VR 遥操作 | ❌ 不匹配 |
| 确定性场景（可重现） | 人类操作者，每次不同 | ❌ 不匹配 |
| 批量运行（无人值守） | 需要操作者在环 | ❌ 不匹配 |
| 手臂动作（wave/extend） | 人类操作者实时输入 | ❌ 过度设计 |
| Isaac Lab 集成 | 需要 IsaacGym | ❌ 不同框架 |

## 结论

**AMO 不适用于 GMDisturb。** AMO 是为人类遥操作设计的全身控制系统，
GMDisturb 需要的是确定性、脚本化、批量的扰动生成框架。
两者在目标、接口、运行环境和算法需求上均不兼容。

## 灵巧手选型参考

GMDisturb 当前使用 G1 被动手臂 + 关节空间硬编码动作。
未来如需升级到灵巧手，Isaac Lab 提供两条现成路径：

| 方案 | USD | 拾取放置任务 | 遥操作 | DOF |
|------|-----|------------|--------|-----|
| G1 + Dex3-1 (G1_29DOF_CFG) | ✅ IsaacLab Nucleus | ❌ | ✅ XR retargeting | 29 base + 14 hand = 43 |
| G1 + Inspire (G1_INSPIRE_FTP_CFG) | ✅ IsaacLab Nucleus | ✅ 已实现 | ✅ XR + ManusVive | 29 base + 24 hand = 53 |

但灵巧手**不解决 GMDisturb 的核心瓶颈**：G1 手臂高度 vs UR10e 桌面工作区的垂直间隙。
灵巧手增加了抓取/操作能力，但手仍然在同样的空间位置。
对安全门测试（距离阈值）无增益。

## 参考

- AMO 论文: https://arxiv.org/abs/2505.03738
- AMO 代码: https://github.com/OpenTeleVision/AMO
- G1_INSPIRE_FTP_CFG: `/root/gpufree-data/IsaacLab/source/isaaclab_assets/isaaclab_assets/robots/unitree.py`
- Isaac Lab G1 pick-place: `pickplace_unitree_g1_inspire_hand_env_cfg.py`
- Unitree Dex3-1: https://www.unitree.com/cn/Dex3-1
