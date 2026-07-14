# 常见故障排查

## 前端显示 `Failed to fetch`

确认后端健康检查返回 `200`，并确认 `NEXT_PUBLIC_API_BASE_URL` 与浏览器访问地址一致。开发环境默认允许 `http://localhost:3000` 访问后端。

## 任务停在失败或需要补充信息

查看页面中的公开执行步骤和错误消息。`requires_input` 表示问题缺少必要业务范围；不要通过浏览器提交 SQL。若为 SQL 错误，Agent 最多执行三次查询（初始一次和两次修复）。

## 跨 schema JOIN 被拒绝

确认 `.env` 的 `ALLOWED_TABLES` 同时包含所需 schema，例如 `dm.*,dw.*`，并在问题或 SQL 中使用完整名称 `dm.orders`、`dw.products`。只配置 `orders` 不会授权 `dm.orders`。

## 外部 MySQL 无法连接或没有表

确认连接 URL 的密码已 URL 编码、账号仍为只读账号、目标 schema 在 `ALLOWED_TABLES` 中，并运行外部只读验收命令。该项目的任务状态存储在单个进程内，重启后旧任务会返回 `TASK_NOT_FOUND`，这是 MVP 的已知限制。

## 安全与密钥

不要将 `.env`、真实连接 URL、模型密钥、原始数据库错误或控制台输出提交到仓库。前端和 API 只显示已脱敏的状态、步骤和错误信息。
