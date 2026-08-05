# 当前分支状态

更新时间：2026-08-05 Asia/Shanghai

## 分支

- 当前分支：`feature/docker-runtime-cleanup`
- 基线：`Agentic-GenBI`
- 合并状态：`feature/session-management` 已通过 merge commit `53a857c` 合入 `Agentic-GenBI`，并已推送到 Gitee / 同步到 GitHub。
- 本轮目标：在已合并的主开发分支基础上，单独切分支做低风险 Docker runtime 清理。

## 本轮已处理

1. Session management 合入主开发分支
   - `feature/session-management` 已合并到 `Agentic-GenBI`。
   - 合并后 `Agentic-GenBI` 已推送到 Gitee。
   - 镜像仓库已执行 Gitee → GitHub 同步。

2. Docker runtime 清理
   - 新建 `feature/docker-runtime-cleanup` 分支。
   - `backend` compose 环境显式固定：
     - `GENBI_BACKEND_WORKERS=1`
     - `UVICORN_WORKERS=1`
     - `WEB_CONCURRENCY=1`
   - `frontend` compose 不再加载整份 `.env`，只保留前端运行所需变量。
   - `frontend` compose 启动命令去掉每次启动时的 `npm install`，依赖改由镜像构建阶段提供。

## 已验证

- 合并后后端相关回归：
  - `python -m pytest backend\tests\test_codex_projection_store_purity.py backend\tests\test_postgres_p0_compat.py backend\tests\test_codex_sdk_runner.py backend\tests\test_analysis_api.py -q`
  - 107 passed，3 subtests passed
- 合并后前端客户端回归：
  - `npm.cmd test -- analysis-backend-client.test.ts`
  - 29 passed
- `docker compose config`
  - passed
- `docker compose build frontend`
  - passed
- `docker compose build backend`
  - passed
- `git diff --check`
  - passed

测试警告：

- 本机 pytest cache 目录无写权限；不影响测试结果。
- Docker CLI 读取 `C:\Users\Jason\.docker\config.json` 无权限；不影响本次 `config` / `build` 结果。

## 尚未处理

1. 跨进程 turn registry
   - V1 已通过单 worker guard 阻断多 worker。
   - 后续如果要支持多 worker，需要 Redis/数据库级 live turn registry 或 reconciliation。

2. FineReport stash
   - 合并前保存了未提交改动：`stash@{0}: wip finereport profile index before session merge`。
   - 该 stash 包含 `docs/plans/current.md` 与 `scripts/finereport/build_profile_index.py` 的后续改动；本轮未恢复，避免污染 Docker 分支。

## 下一步

1. 如需继续验证 Docker runtime，可执行 `docker compose up -d --build` 后做服务级 smoke。
2. Docker 分支验证稳定后再提交 / 推送。
