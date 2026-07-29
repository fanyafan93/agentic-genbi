# 当前任务

更新时间：2026-07-29（Asia/Shanghai）

## 当前状态

- 仓库：`E:\my_repo\agentic genbi`
- 分支：`feature/knowledge-base-ui`
- 当前切片：把知识探索里的“知识沉淀”扩展为可交互的“知识库”模块，并补基础后端知识资产 API。
- 工作区注意：本轮改动集中在知识库 UI、知识库 API、测试和边界文档。

## 本轮变更

- 新增 `frontend/src/modules/knowledge-base/` 领域模块：
  - `types.ts`：统一 `KnowledgeBaseItem`，覆盖语义层、探索沉淀和治理字段。
  - `mock.ts`：提供指标、字段映射、报表逻辑、维度和冲突口径的演示知识。
  - `logic.ts`：提供筛选、标签汇总、后端记录映射和保存 payload 构建。
  - `api.ts`：读取、创建、更新知识库记录，并读取后端标签。
  - `components/KnowledgeBase.tsx`：实现知识库三栏 UI。
- 知识库 UI 提供 5 个主 tab：`全部知识`、`语义层`、`探索沉淀`、`认证中心`、`标签体系`。
- 知识库 UI 提供左侧分类/标签/状态/负责人筛选，中间知识列表，右侧详情与编辑面板。
- 知识详情包含概览、语义定义、证据与来源、关联对象、认证记录、版本历史和 Agent 使用记录。
- 支持新建知识、编辑知识、切换认证状态、按当前分类新建、标签体系跳转筛选。
- 知识探索第三个 tab 从“知识沉淀”改为“知识库”；探索中的保存动作文案改为“保存到知识库”。
- 清理了知识探索旧动作名，前端消息 action 只保留“保存到知识库”。
- 知识探索右侧主区切换采用方案 A：保留现有探索、资源库、知识库各自 UI，不统一工作区外壳；主区切换时旧内容先淡出、新内容再淡入，并支持 `prefers-reduced-motion`。
- “我的探索”任务切换改为会话卡片堆：选中探索会话滚到前景，其他探索会话以偏移、缩放和透明度堆叠在后方；保留消息详情、等待状态和“保存到知识库”动作。
- 会话卡片堆新增视觉选中态步进：真实选中会话立即更新，前景卡片按相邻索引快速滚动到目标会话，并在落位时淡入标题、消息和输入框。
- 会话卡片堆过渡加大为电影卡片效果：前景卡片会按方向横向滑出，目标卡片从后方高亮放大进入，后方卡片堆同步错位。
- 会话卡片舞台比例调整：保留背景作为舞台，主卡片约占背景宽度 3/4；卡片堆允许在主卡容器外露出边缘，以恢复电影卡片的层叠切换感。
- 新建探索时会把草稿探索临时插入卡片堆，立即展示一张完整空会话卡片和提示；切换动画期间只渲染轻量卡片封面，目标卡片落位后再渲染完整会话内容，降低卡顿。
- 会话卡片舞台继续收紧横向空隙：主卡片宽度提高到 `min(1080px, 86%)`，卡片内部左右 padding 降低到最大 `46px`，保留少量背景留白但减少内容压缩。
- 探索会话前端类型新增 `createdAt` 和 `lastMessageAt`；后端运行摘要和事件流映射会保留创建时间、最后会话时间，并显示到分钟。
- “我的探索”左侧列表按最后会话时间倒序展示，列表时间显示最后会话时间；卡片详情头部显示创建时间。
- 会话卡片内部消息展示改回主分支的探索消息样式：使用 `exploration-message`、`message-avatar`、`message-bubble` 和 `message-title` 结构；外层电影卡片堆保持不变。
- 探索保存知识时默认写入治理元数据：`type=verified_conclusion`、`status=pending`、`visibility=team`、`tags=["探索沉淀"]`、`agent_visible=true`。
- 后端 `KnowledgeStore` 新增知识搜索、更新和标签汇总能力；JSONL 测试存储与 Postgres 存储保持同一接口。
- 后端 `/api/knowledge` 支持 `q/type/status/tag/owner/limit` 筛选；新增 `PATCH /api/knowledge/{id}` 和 `GET /api/knowledge/tags`。
- Postgres 仍复用 `verified_knowledge.metadata JSONB` 承载知识库扩展字段，未引入新表或迁移。

## 已验证

- `python -m unittest backend.tests.test_knowledge_store backend.tests.test_exploration_api -v`：16 个后端相关测试通过。
- `python -m unittest discover -s backend\tests -v`：74 个后端测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：方案 A 切换动效落地后，39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：方案 A 两段式切换调整后，39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：探索会话卡片堆调整后，39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：会话卡片堆步进过渡调整后，39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：电影卡片式过渡加大后，39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：3/4 卡片舞台与卡片堆外露调整后，39 个前端相关测试通过。
- `cmd /c npm run test -- knowledge-base investigation-events`：新建探索草稿卡片与轻量切换渲染调整后，39 个前端相关测试通过。
- `cmd /c npm run test`：会话时间与卡片间距调整后，4 个前端测试文件、42 个测试通过。
- `cmd /c npm run test`：卡片内部消息展示改回主分支样式后，4 个前端测试文件、42 个测试通过。
- `cmd /c npm run test`：4 个前端测试文件、42 个测试通过。
- `cmd /c npm run build`：方案 A 切换动效落地后，Next.js 构建通过。
- `cmd /c npm run build`：方案 A 两段式切换调整后，Next.js 构建通过。
- `cmd /c npm run build`：探索会话卡片堆调整后，Next.js 构建通过。
- `cmd /c npm run build`：会话卡片堆步进过渡调整后，Next.js 构建通过。
- `cmd /c npm run build`：电影卡片式过渡加大后，Next.js 构建通过。
- `cmd /c npm run build`：3/4 卡片舞台与卡片堆外露调整后，Next.js 构建通过。
- `cmd /c npm run build`：新建探索草稿卡片与轻量切换渲染调整后，Next.js 构建通过。
- `cmd /c npm run build`：会话时间与卡片间距调整后，Next.js 构建通过。
- `cmd /c npm run build`：卡片内部消息展示改回主分支样式后，Next.js 构建通过。
- `docker compose restart frontend`：前端容器 `agentic-genbi-frontend-1` 已重启并重新启动。
- `docker compose config --quiet`：Compose 配置可解析；出现 Docker 用户级配置读取权限警告 `C:\Users\Jason\.docker\config.json: Access is denied`，但命令返回成功。
- Chrome DevTools MCP 可打开 `http://192.168.101.12:3000/`，但当前 Chrome 未登录，只验证到登录页，未完成登录态下的视觉检查。

## 边界与风险

- 当前知识库后端基础能力复用 `verified_knowledge.metadata`；这是适合 demo 的演进方式，但未来正式知识库仍需要独立表结构、索引、权限和版本表。
- 知识库 UI 有完整交互，但导入、批量打标、细粒度权限、正式审批流和 Agent 引用审计仍是前端占位或本地状态。
- 当前未完成登录态浏览器视觉验证，需要用户登录后再用 Chrome DevTools 或 Playwright 做一次真实页面检查。

## 下一步

1. 登录态下验证知识库页面布局和交互，按实际观感微调密度与按钮位置。
2. 设计正式知识库数据库模型：`knowledge_items`、`knowledge_versions`、`knowledge_approvals`、`knowledge_tags`、`knowledge_usage_events`。
3. 把知识探索里的“保存到知识库”改成可选择保存类型的弹层，而不是默认保存为探索结论。
