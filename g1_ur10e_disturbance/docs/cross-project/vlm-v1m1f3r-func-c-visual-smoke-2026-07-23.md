# V1-M1F3R Canonical Func-C Visual Smoke（2026-07-23）

结论：**VISUAL_REVIEW_REQUIRED**（未授予 technical_visual_pass）

## 基线与门禁
- HEAD：`b7034031beba3b4f7cdc0b85b1b5defd686302b1`
- origin/main：`b7034031beba3b4f7cdc0b85b1b5defd686302b1`
- HEAD=origin：`true`
- 前置测试：`test_e01_func_c_capture_unit` = `16 passed`
- provenance/fail-closed：`2 passed`
- audit：`gate_passed=true`

## 一次性预算执行
- Build（仅 1 次）：`docker build -f GMRobot/docker/Dockerfile.e01-func-c-m1f3r -t gmdisturb:e01-func-c-visual-m1f3r-20260723 GMRobot`
- Build exit：`0`
- Image 完整 SHA：`sha256:0fa40c934133a34ed2740382eac5c301b2994775232ce585b00b9136a4e86e8c`
- Smoke（仅 1 次）exit：`0`

## 证据路径
- 结果目录：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_visual_smoke_m1f3r_20260723`
- 原图绝对路径（待人工复核）：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_visual_smoke_m1f3r_20260723/scene/frame_000000_env0.png`
- Frame SHA256：`a5155db466dcca5c9cff64a1828843b325ba1b89766c5f2f36450bd716fcb5c5`
- Dockerfile SHA256：`a6497334e9e86721d7131b1a649294ce5274a16899134a3b51e30ed9451486d4`
- 旧坏图：`/home/czz/GMrobot/g1_ur10e_disturbance/results/paper_demo/v1e01_func_c_capture_20260722/scene/frame_000200_env0.png`
- 旧坏图 SHA256：`72b5c1167f59b56d997ccce24346ebcccaf1050e9429f7c04bc633a6462cd89c`

## 自动门禁（脚本）
- PNG 有效非黑：`True`
- 左箱 ROI 存在：`True`
- 右箱 ROI 存在：`True`
- 右箱内容 ROI 存在：`True`
- 右箱内容存在：`True`
- 无 Traceback / DEVICE_LOST / 新 Xid：`True` / `True` / `True`
- POST=0：`True`
- 无残留：`True`

## Spawn / Camera 记录
- box_A spawn asset：`/home/czz/GMrobot/GMRobot/source/GMRobot/GMRobot/assets/container_fixed.usd`
- box_A spawn SHA256：`acb2151a26baee9ff27dcdfe9c8c5bf2919182747389160f3f621347dc2a057d`
- box_B spawn asset：`/home/czz/GMrobot/GMRobot/source/GMRobot/GMRobot/assets/container_full_visual.usd`
- box_B spawn SHA256：`f392dff221a280f0cd831ab1b37f5d9b22fab3da4b246fb65ed9b7498c3c9c6e`
- camera pose：`pos=[0.35, 0.0, 2.5] rot=[0.7071, 0.0, 0.7071, 0.0]`

## 约束符合性
- 未执行正式 Func-C 重采集
- 未使用网络/POST/VLM/perception/SAM2/GDINO/five-stage/凭据
- 不覆盖历史 tag 与历史结果

> 按要求先保持 `VISUAL_REVIEW_REQUIRED`。仅主agent另行人工确认后，才可设置 technical_visual_pass。
