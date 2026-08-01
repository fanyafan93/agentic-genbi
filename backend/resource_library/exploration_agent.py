from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .database_tools import DatabaseConfig, ReadonlyDatabaseTools
from .knowledge_store import KnowledgeStore
from .tools import ResourceLibrary


DATA_EXPLORATION_AGENT_INSTRUCTIONS = """
你的固定身份名称是：Agentic GenBI 知识探索 Agent。
服务对象是 BI 分析师和运营人员。

你的任务不是直接生成 Artifact、数据报表、数据集或可复用 Agent；你的任务是围绕一个业务问题，
在资源库、数据库元数据和已有知识中查证公司已有实现、业务口径、字段来源和证据链，最后沉淀为可复用知识。
你只探索知识，不负责替用户完成业务统计、占比分析、透视明细或正式数据交付。
对外只能自称“知识探索 Agent”或“Agentic GenBI 知识探索 Agent”。
禁止自称“数据探索 Agent”，也不要把自己描述成数据分析执行 Agent。
如果用户问“你是谁”“你是什么 Agent”“你有什么工具”或只是打招呼，要基于当前会话自然回答，不使用固定模板；可以简短说明你是知识探索 Agent，并引导用户给出具体业务问题。

工作方式：
1. 先根据用户问题生成一个简短中文标题，标题描述业务问题本身，不使用执行 Agent 的名字。
2. 优先搜索资源库，查找已有报表、SQL、ETL、数据字典、CPT、Apache Hop 文件和历史实现。
3. 对候选资源先查看结构摘要；只有需要核验证据时，才读取受控片段。
4. 再搜索数据库表和字段元数据，确认表、字段、口径和可能的数据链路；这一步是为了查证知识，不是为了直接出统计结果。
5. 验证候选表或字段是否仍可作为当前知识证据时，先用 inspect_table_profile 查看近似行数、表大小、更新时间、分区信息和时间字段候选；不要默认执行 count(*)。
6. 验证知识结论和口径有效性时，必须优先使用最近 3-6 个月、最近完整月份或最近可用分区/日期的证据；如果候选资源或数据只对应几年前，或更新时间明显陈旧，必须明确说明这只能证明历史实现，不能证明当前口径仍适用，并继续寻找更新表、更新分区、更新报表或更新知识。
7. 只有元数据和资源摘要不足，且确实需要核验证据、对账线索或排除歧义时，才调用业务只读 SQL；SQL 只用于有限验证知识，不用于替用户产出业务统计结果，必须说明查询理由，并优先限定在最近数据窗口。
8. 遇到会显著影响结果的口径分支时，必须先向用户追问并等待确认，而不是继续猜测；例如分母定义、是否含退款/爆品/未支付订单、时间粒度、用户去重口径、平台/店铺范围、是否需要明细导出。
9. 每个结论都必须带证据引用：resource_id、相对路径、表名或字段名。
10. 不要编造不存在的文件、表、字段、指标口径或验证结果。
11. 输出过程应适合前端展示为“探索会话 Agent”：用户问题、探索步骤、工具结果摘要、折叠证据、追问、最终结论。
12. 只有用户确认或证据足够稳定时，才调用 save_verified_knowledge 沉淀知识。
13. 一旦已有证据足以回答、或遇到必须由用户决定的口径分支，就输出结论或追问并停止；不要为了继续查证而反复调用工具。

安全边界：
- search_resources 和 inspect_resource 不返回完整文件正文。
- read_resource_excerpt 只能读取明确资源 ID 的有限片段。
- run_readonly_query 只能运行单条只读 SQL，并由服务端校验、限行和审计。
- 任何敏感信息、密码、连接串或个人数据都不能写入知识沉淀。
""".strip()


def create_data_exploration_tool_functions(
    *,
    resource_library: ResourceLibrary | None = None,
    db_tools: ReadonlyDatabaseTools | None = None,
    knowledge_store: KnowledgeStore | None = None,
) -> list[Callable[..., dict[str, Any]]]:
    library = resource_library or ResourceLibrary()
    database = db_tools or ReadonlyDatabaseTools(DatabaseConfig.from_env())
    store = knowledge_store or KnowledgeStore()

    def search_resources(query: str, resource_type: str | None = None, limit: int = 10) -> dict[str, Any]:
        """Search indexed resource-library metadata and structural summaries."""
        results = library.search_resources(query, resource_type=resource_type or None, limit=limit)
        return {"results": [_compact_dataclass(result) for result in results]}

    def inspect_resource(resource_id: str) -> dict[str, Any]:
        """Inspect one resource structural summary without returning its full body."""
        return _compact_dataclass(library.inspect_resource(resource_id))

    def read_resource_excerpt(
        resource_id: str,
        section: str = "head",
        query: str | None = None,
        max_lines: int = 120,
    ) -> dict[str, Any]:
        """Read a bounded excerpt from one explicit resource id."""
        excerpt = library.read_resource_excerpt(
            resource_id,
            section=section,
            query=query,
            max_lines=min(max_lines, 240),
        )
        return _compact_dataclass(excerpt)

    def search_db_tables(keyword: str, database_schema: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Search MySQL information_schema tables by table name or comment."""
        return _compact_dataclass(database.search_db_tables(keyword, schema=database_schema or None, limit=limit))

    def get_table_schema(database_schema: str, table: str) -> dict[str, Any]:
        """Return columns and comments for one MySQL table."""
        return _compact_dataclass(database.get_table_schema(database_schema, table))

    def inspect_table_profile(database_schema: str, table: str) -> dict[str, Any]:
        """Inspect approximate row count, table size, update time, partitions, and likely time columns from MySQL metadata."""
        return _compact_dataclass(database.inspect_table_profile(database_schema, table))

    def run_readonly_query(sql: str, reason: str, max_rows: int | None = None) -> dict[str, Any]:
        """Run a server-validated, bounded, readonly business-data SQL query."""
        return _compact_dataclass(database.run_readonly_query(sql, reason=reason, max_rows=max_rows))

    def save_verified_knowledge(
        title: str,
        question: str,
        conclusion: str,
        scope: str,
        verification: str,
        evidence_refs: list[str],
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one verified conclusion as reusable exploration knowledge."""
        record = store.save_verified_knowledge(
            title=title,
            question=question,
            conclusion=conclusion,
            scope=scope,
            verification=verification,
            evidence_refs=evidence_refs,
            run_id=run_id,
        )
        return _compact_dataclass(record)

    return [
        search_resources,
        inspect_resource,
        read_resource_excerpt,
        search_db_tables,
        get_table_schema,
        inspect_table_profile,
        run_readonly_query,
        save_verified_knowledge,
    ]


def _compact_dataclass(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise TypeError(f"Expected dataclass or dict, got {type(value).__name__}")


def default_resource_library(
    *,
    index_path: Path = Path(".resource-index/resources.json"),
    summary_path: Path = Path(".resource-index/resource-summaries.json"),
) -> ResourceLibrary:
    return ResourceLibrary(index_path=index_path, summary_path=summary_path)
