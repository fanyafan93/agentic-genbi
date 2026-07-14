# Task 6 and Task 8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现受控元数据发现与 MiniMax 结构化 Agent 报告，保持动态 SQL 路径关闭。

**Completed tasks:**

- [x] 新增 Pydantic 元数据契约、`app.database.metadata` 和白名单工具包装器；测试白名单过滤、稳定列属性与隐藏表脱敏。
- [x] 锁定 `openai-agents==0.18.2`，通过 MiniMax OpenAI 兼容 Chat Completions 运行单 Agent；由于 M 系列不支持原生 JSON Schema，runner 以 Pydantic 校验 Agent 提示出的 JSON。
- [x] 服务端使用固定查询结果组装最终 `AnalysisReport`，避免模型改写 SQL、表格、耗时或尝试次数。
- [x] 映射 `PROVIDER_NOT_CONFIGURED`、`PROVIDER_ERROR` 与 `INVALID_REPORT`，常规测试使用 fake runner。
- [x] 更新 Docker 环境注入、示例配置、README、项目计划与交接文档；Task 7 保持待办。
