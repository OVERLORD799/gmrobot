# V1-C1R-P0 Canonical package import 修复（2026-07-22）

## 结论

| 项 | 值 |
|---|---|
| 根因 | `semantic_bridge.py` 使用顶层 `from safety…`；Docker editable install 无顶层 `safety` 包 |
| 修复 | 改为 `from GMRobot.safety…`；`shadow.SemanticShadowBridge` 惰性导出；`GMRobot/__init__.py` 对缺 Isaac/`pxr` 容错 |
| 新镜像 | `gmdisturb:semantic-shadow-v1c0p1-20260722` |
| image_id | `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c` |
| e516c78e | **未覆盖**；标注为 live semantic import **INVALID** |
| 正式 V1-C1R / POST / V1-D | **未执行** |
| 本轮性质 | **代码修复轮次**，非正式实验 |

---

## 1. 精确根因

V1-C1R FAIL（`ModuleNotFoundError: No module named 'safety'`）因：

```text
GMRobot/shadow/semantic_bridge.py
  from safety.semantic_supervisor import ...
  from safety.semantic_supervisor_logger import ...
```

宿主机单测把 `…/GMRobot/GMRobot` 放进 `sys.path`，伪造了顶层 `safety`；镜像内仅 editable install `GMRobot` 包，**不存在**顶层 `safety`。

因此：**e516c78e 上 offline semantic isolation PASS、semantic-disabled Isaac smoke PASS，但不能再表述为“镜像已完成实时 semantic 启用验证”。**  
V1-C1R FAIL 保留，原因为 **canonical import packaging bug**。

---

## 2. 改动文件与行

| 文件 | 变更 |
|---|---|
| `shadow/semantic_bridge.py` L12–20 | `GMRobot.safety.semantic_supervisor` / `…_logger` |
| `shadow/__init__.py` | `SemanticShadowBridge` **惰性** `__getattr__`（避免拖垮 `from shadow.*` 离线测试） |
| `GMRobot/__init__.py` | `tasks` / `ui_extension_example` 缺依赖时 `ModuleNotFoundError` 跳过（无 Kit/`pxr` 时可 `import GMRobot`） |
| `scripts/test_canonical_package_import_v1c0p1_unit.py` | **新增** canonical + 源码扫描 + agent import AST |
| `scripts/test_semantic_supervisor_shadow_v1c0_unit.py` | 改为 canonical `GMRobot.*` 导入路径 |

未改：阈值、gateway、scheduler、drain=60 cfg、prompt、endpoint、场景、B0–B4、远端、控制语义。

---

## 3. Canonical import 测试

`test_canonical_package_import_v1c0p1_unit.py`：**4/4 PASS**

- `sys.path` 仅 `GMRobot/source/GMRobot`
- `import GMRobot` + `GMRobot.safety.*` + `GMRobot.shadow.semantic_bridge` + `from GMRobot.shadow import SemanticShadowBridge`
- 模块名以 `GMRobot.safety.` 开头；**不**依赖顶层 `safety`
- 源码树扫描无运行时 `from safety` / `import safety`
- `gm_state_machine_agent` AST 确认 `from GMRobot.shadow.semantic_bridge import SemanticShadowBridge`

---

## 4. 源码扫描

`GMRobot/source/GMRobot/GMRobot/**/*.py`：无顶层 `safety` 导入（`from .mdp import safety_obs` 等相对名除外）。  
`scripts/` 旧兼容导入可暂留（本轮未强制清扫全部脚本）。

---

## 5. 离线测试

过滤：`test_*.py` 排除 `(1)` 副本与 `camera` Isaac 脚本。

| 项 | 值 |
|---|---|
| scripts | **33**（含新增 canonical）全绿 |
| `def test_` 计数 | **350**（约用户所述 ~343 + 本轮新增） |
| 含 five-stage / semantic / session / v0b* | 全绿 |

---

## 6. 新镜像

| 项 | 值 |
|---|---|
| tag | `gmdisturb:semantic-shadow-v1c0p1-20260722` |
| image_id | `sha256:f81e59ce6cac9b66e568246dc58b42828d41cb60e94e984ecbe679fde4ddde7c` |
| created | `2026-07-22T15:40:00.553441175+08:00` |
| git revision | `46a76ad8bd2ad7ad1f0051239dfeaafb96782bc5`（dirty worktree） |
| five-stage v1c1r SHA | `df4e082800aab2bd0d900707be92eee00f7a6c1a60e20bb8c4f7782795de2253`（未改） |
| semantic v1c1r SHA | `03f64250bd715b0327412fd7808bb82acf6198258d3ab49c9c3db68120773ac6`（未改） |
| e516c78e | **unchanged** `sha256:e516c78e…c2ccf1da` |

---

## 7. 镜像内 `module.__file__`

（无宿主机源码 bind-mount 偷渡）

```text
GMRobot  .../GMRobot/__init__.py
sem      GMRobot.safety.semantic_supervisor
         .../GMRobot/safety/semantic_supervisor.py
slog     GMRobot.safety.semantic_supervisor_logger
         .../GMRobot/safety/semantic_supervisor_logger.py
bridge   GMRobot.shadow.semantic_bridge
         .../GMRobot/shadow/semantic_bridge.py
ExportedBridge_same True
V1C0P1_CANONICAL_IMPORT_OK
```

路径均位于 `/opt/projects/GMRobot/source/GMRobot/GMRobot`；顶层 `safety` 不在 `sys.modules`。

---

## 8–11. Smoke / POST / Xid

| 项 | 结果 |
|---|---|
| import/config smoke | **PASS** |
| 1-step Isaac（semantic/five-stage **关**） | exit **0**，PROGRESS=1，`scene_rgb` ready |
| Traceback / ModuleNotFound / DEVICE_LOST | **无** |
| POST | **0** |
| Xid 前→后 | **0 → 0** |

结果目录：`results/paper_demo/v1c0p1_isaac_smoke_20260722/`

未做需 endpoint 的 semantic-on bootstrap（避免 POST）。

---

## 12. e516c78e 降级标注

| 能力 | e516c78e |
|---|---|
| offline semantic isolation | PASS |
| semantic-disabled Isaac smoke | PASS |
| live `--enable_semantic_supervisor_shadow` import | **INVALID**（packaging） |
| 正确表述 | 不得再称“镜像已完成实时 semantic 启用验证” |

正式 live semantic 需使用 **v1c0p1**（`f81e59ce…`），并待批准 **V1-C1R-P1**。

---

## 13. 历史未覆盖

未覆盖：V1-C1 NOT_RUN/FAIL、V1-C1R FAIL、Xid 审计、GPU preflight、perception warming、e516 镜像。  
本轮仅新增修复文档与 v1c0p1 镜像/smoke。

---

## 停止

等待另行批准 **V1-C1R-P1**。不进入 V1-D。
