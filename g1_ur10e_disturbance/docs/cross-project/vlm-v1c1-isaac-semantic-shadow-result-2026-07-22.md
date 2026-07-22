# V1-C1 Isaac semantic supervisor shadow — 前置阻塞（2026-07-22）

## 最终分类：**NOT_RUN / PREFLIGHT_BLOCKED**

未启动 Isaac，未发送 POST，未创建结果目录。  
原因：批准运行所依赖的 **既有 SSH tunnel / localhost health 当前不可用**；按约束禁止创建/修改 tunnel、禁止读取凭据。

| 检查 | 结果 |
|---|---|
| 镜像 ID | `sha256:e516c78…` **匹配** |
| `/tmp/gmrobot-v0b2-tunnel.sock` | **缺失** |
| `GET :18080/health` | **连接失败** |
| `GET :18082/health` | **连接失败** |
| `ss` 监听 18080/18082 | **无** |
| 结果目录 `v1c1_isaac_semantic_shadow_20260722` | **未创建**（避免污染只跑一次门禁） |
| 代码/阈值/远端 | **未改** |
| POST | **0** |

已就绪（未执行）：

- runtime five-stage config：`GMRobot/configs/five_stage_shadow_legacy_gateway_v1c1.yaml`
- semantic config（不变）：`semantic_safety_supervisor_shadow_live.yaml`
- 镜像：`gmdisturb:semantic-shadow-v1c0-20260722`

## 恢复后需外部完成

由外部重建既有 tunnel（本 agent 不执行）：

- sock：`/tmp/gmrobot-v0b2-tunnel.sock`
- health：`http://127.0.0.1:18080/health` 与 `:18082/health` 返回 ok

然后重新批准一次正式 V1-C1（仍最多 6 POST，仍只跑一次）。

## 正确表述

**真实语义 advisory 在线评估未开始：前置 tunnel/health 阻塞；无控制副作用、无 POST。**
