# V1-W0.1 提交前最小修复与计划校正报告（2026-07-22）

## 1. Import 精确修复

| 文件 | 修复 |
|---|---|
| `safety/semantic_supervisor.py` | 仅 `from .semantic_key_v2 import build_semantic_key_v2` |
| `shadow/five_stage_worker.py` | 仅 `GMRobot.vlm.*` / `GMRobot.safety.semantic_temporal_fusion` |
| `safety/semantic_temporal_fusion.py` | 仅 `GMRobot.vlm.*` |
| `safety/semantic_key_v2.py` | 仅 `GMRobot.vlm.temporal_evidence` |
| `scripts/test_v1d2a_temporal_fusion_unit.py` | `GMRobot.*` + torch stub |

## 2. canonical 扫描

runtime `from/import safety|vlm` **offenders=0**

## 3. replan 正确 CWD

CWD=`/home/czz/GMrobot/GMRobot` → exit 0；根因=**wrong_working_directory**（YAML 存在）

## 4–5. 测试对照

| 轮次 | 结果 |
|---|---|
| initial (W0) | **32/34** |
| final (W0.1) | **34/34** |

## 6. Commit 依赖图

`commit1 → commit2 → commit3 → commit4 → commit5 → commit6`

- commit2：**无** `semantic_bridge`；含 worker（temporal 默认关）
- commit3：supervisor + **semantic_bridge** + agent
- commit4：temporal 模块/配置/fixtures

路径数：`{'commit1': 12, 'commit2': 7, 'commit3': 12, 'commit4': 26, 'commit5': 53, 'commit6': 94}`

## 7. stage/unstage

一致=True；n=204；无 add ./-A/-f；无 results/token/pyc

## 8–9. 敏感 / staged

security_review_required=False；token tracked=False；**staged=0**；cached empty=True

## 10. git diff --stat

```
 GMRobot/configs/perception_client.yaml             |   1 +
 GMRobot/configs/vlm_client.yaml                    |   3 +
 GMRobot/deploy/ai_server/vlm_service.py            | 119 +++++-----
 GMRobot/scripts/gm_state_machine_agent.py          | 249 +++++++++++++++++++++
 GMRobot/source/GMRobot/GMRobot/__init__.py         |  14 +-
 .../source/GMRobot/GMRobot/perception/__init__.py  |  20 +-
 .../source/GMRobot/GMRobot/perception/client.py    | 101 ++++++++-
 .../tasks/manager_based/gmrobot/gmrobot_env_cfg.py |   5 +
 GMRobot/source/GMRobot/GMRobot/vlm/__init__.py     |  47 +++-
 GMRobot/source/GMRobot/GMRobot/vlm/client.py       | 149 ++++++++++--
 10 files changed, 628 insertions(+), 80 deletions(-)

```

porcelain=159 modified≈10 untracked≈149

**未执行** stage/add/commit/push。等待批准暂存。
