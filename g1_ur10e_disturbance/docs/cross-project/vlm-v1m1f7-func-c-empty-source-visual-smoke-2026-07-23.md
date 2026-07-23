# V1-M1F7 Func-C visual-only 去遮挡修复：source-only build + 单次 visual smoke（2026-07-23）

结论：`SMOKE_STARTUP_FAIL_FINAL`（唯一 smoke 已失败，未重试）；`next_gate=FIX_VALIDATION_CONTEXT_ONLY`。

## 前置核验（执行前）
- HEAD：`86b07d0`（完整匹配）
- origin/main 一致：`true`
- worktree clean：`true`
- M1F6 tests + manifest：`PASS`

## 一次性预算执行（无重试）
- Build（1/1）：`gmdisturb:e01-func-c-empty-source-m1f7-20260723`，Dockerfile 仅 `COPY`，exit=`0`
- Isaac/AppLauncher smoke（1/1）：exit=`1`，未重试

## 失败点（唯一运行）
- 结果目录：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_empty_source_smoke_m1f7_20260723`
- 失败阶段：预断言脚本阶段（仿真未启动）
- 失败原因：`ModuleNotFoundError: No module named 'pxr'`
- 由于唯一 smoke 失败，未生成可用顶视 RGB 与 runtime prim counts（`Part_* count=0` / `ContainerA/GridA/ContainerB` 无法在本次运行中完成落盘）

## 必要追踪信息（已记录）
- image SHA：`sha256:9465a5115ab3c416c6a0481ff12945c222092ed31c248df1387561db2f6b9731`
- source `container.usd` SHA：`ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9`
- reference frame330 SHA：`6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- M1F5 rejected frame SHA：`a5155db466dcca5c9cff64a1828843b325ba1b89766c5f2f36450bd716fcb5c5`
- camera：`pos=[0.35,0.0,2.5] rot=[0.7071,0.0,0.7071,0.0]`
- GPU：`NVIDIA GeForce RTX 5090 Laptop GPU`
- Xid：当前驱动 CLI 不支持 `nvidia-smi -q -d XID`，`dmesg` 前后均 0 行 Xid

## 门禁状态
- `exit0`：FAIL
- `PNG非黑`：FAIL（无帧）
- `双箱ROI`：FAIL（无帧）
- `右满箱内容`：FAIL（无帧）
- `Part count0`：FAIL（运行时审计未写出）
- `POST0`：FAIL（运行提前失败，未完成流程）
- `无Traceback`：FAIL（出现 Traceback）
- `无DEVICE_LOST/newXid/residual`：PASS

## 状态修正
- raw 启动失败与 frame 缺失事实保留
- 不伪称 visual review
- 下一门禁：`FIX_VALIDATION_CONTEXT_ONLY`
