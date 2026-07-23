# V1-M1F5 reference-locked Func-C 左箱 source-only build + 单次 visual smoke（2026-07-23）

结论：`VISUAL_REVIEW_REQUIRED`（按约束不自动给视觉 PASS；需与 reference `frame_000330_env0` 人工并排复核）

## 前置核验（全部通过）
- HEAD：`d8f20a1f6ad3b0270e65309cc851ef2b8c947a39`
- `origin/main` 一致：`true`
- worktree clean：`true`
- M1F4 门禁：
  - `manifest validator`：PASS
  - `GMRobot/scripts/test_e01_func_c_capture_unit.py`：17 tests，PASS

## 一次性预算执行（无重试）
- Build（1/1）：
  - Dockerfile：`GMRobot/docker/Dockerfile.e01-func-c-reference-bin-m1f5`
  - 约束：仅 `COPY` 源码/资产/配置；无 `pip`/quarantine/依赖修改
  - tag：`gmdisturb:e01-func-c-reference-bin-m1f5-20260723`
  - image SHA：`sha256:caec76f07e57a3cbdcc6dd54552ea7e71f83118dbf7be6d043ec239045bdf29e`
  - exit：`0`
- Isaac/AppLauncher smoke（1/1）：`exit=0`

## 结果与证据
- 结果目录：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_reference_bin_smoke_m1f5_20260723`
- 新 frame 绝对路径：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_reference_bin_smoke_m1f5_20260723/scene/frame_000000_env0.png`
- 新 frame SHA256：`790f1d70bd5affc915c30dae64a9eddd0f1e8981509eb687c32a0223e246fedb`
- reference frame：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_dyn_b_formal_m1z9_20260723/scene/frame_000330_env0.png`
  - SHA256：`6e2d3351554fa6db86599e8bd9f71b0caf32d03ba6af3144661b8a637ca30a9a`
- rejected frame：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_visual_smoke_m1f3r_20260723/scene/frame_000000_env0.png`
  - SHA256：`a5155db466dcca5c9cff64a1828843b325ba1b89766c5f2f36450bd716fcb5c5`

## ContainerA 参考锁定断言
- source asset path：`/home/czz/GMrobot/GMRobot/source/GMRobot/GMRobot/assets/container.usd`
- source asset SHA256：`ee307082665bb316eb53965861f8ca635a8e922aa8f90805126faf9cc75493a9`
- 断言结果：`containerA_asset_identity_assertion=true`（与要求 SHA 完全一致）
- scale：`(0.01, 0.01, 0.01)`；orientation quat(wxyz)：`(0.5, 0.5, 0.5, 0.5)`，与 M1F4 一致
- `container_full_visual.usd` SHA256：`f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e`

## Camera / GPU / Xid
- camera pose：`pos=[0.35, 0.0, 2.5] rot=[0.7071, 0.0, 0.7071, 0.0]`
- GPU Xid pre：`.../meta/gpu_xid_pre.txt`
- GPU Xid post：`.../meta/gpu_xid_post.txt`
- 新增 Xid：`false`（pre=0, post=0）

## 自动门禁
- `exit=0`：PASS
- PNG 有效：PASS
- 双箱 ROI 存在（左 source + 右 target）：PASS
- 右箱内容存在：PASS
- `POST=0`：PASS
- 无 `Traceback` / `DEVICE_LOST` / 新 Xid / residual：PASS

## 人工并排复核要求（主agent后续执行）
- 必须将新 frame 与 `reference frame_000330_env0` 并排检查：
  - 左箱绿色框
  - 白色规则栅格
  - 比例/朝向一致
  - 不得出现白色托架/阶梯/扇形/爆炸
- 在人工复核完成前，保持 `VISUAL_REVIEW_REQUIRED`。
