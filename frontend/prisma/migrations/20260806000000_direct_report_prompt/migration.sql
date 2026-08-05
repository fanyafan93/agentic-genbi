UPDATE "SystemPromptVersion"
SET "status" = 'archived'
WHERE "promptKey" = 'analysis_system'
  AND "status" = 'published';

INSERT INTO "SystemPromptVersion" (
    "id",
    "promptKey",
    "name",
    "description",
    "version",
    "content",
    "status",
    "createdById",
    "publishedAt"
) VALUES (
    'system-analysis-prompt-v2-direct-report',
    'analysis_system',
    '分析系统提示词',
    '控制分析任务的数据核验、Report 生成和回复约束。',
    2,
    E'围绕用户提出的业务问题推进分析。\n- 涉及真实业务数据时，必须先查证，不能编造表、字段、指标、金额、占比或增长结论。\n- Report 只输出有据可查的数据和明确下一步建议。\n- 生成 Report 时保存 layout、filters、charts、tables、queries；queries 保存只读 SQL 和筛选参数绑定，不内嵌查询结果行。\n- 新建 Report 调用 GenBI_report.create_report；修改当前 Report 调用 GenBI_report.update_report，并传入完整 Report 配置。\n- 不要把完整 Report 正文写在聊天回复中。\n- 输出中文。',
    'published',
    'system',
    CURRENT_TIMESTAMP
);
