# V1-D9.1：D9 S1+S2 批次人工标签审查（2026-07-24）

审查人：用户（明确批复"批准"，2026-07-24）。
审查材料：每 seed 一张 4 窗口首末帧拼图（v1d9_review_packet_20260724/review_seed{46,47,48}.png）。
审查判据：approach 行 G1 可见变小/移动、dyn_sweep 行可见横移、retreat 行可见变大、static_idle 行基本静止。

结论：12 个候选全部批准。manifest 升至 3.8.0。
- 动态正样本组：+9（dyn_sweep×3、approach×3、retreat×3），总计 13。
- 静态负样本组：+3（static_idle×3），总计 4。
