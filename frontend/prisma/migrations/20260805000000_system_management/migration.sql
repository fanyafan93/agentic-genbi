ALTER TABLE "User"
ADD COLUMN "status" TEXT NOT NULL DEFAULT 'active';

CREATE TABLE "SystemPromptVersion" (
    "id" TEXT NOT NULL,
    "promptKey" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "version" INTEGER NOT NULL,
    "content" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'draft',
    "createdById" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "publishedAt" TIMESTAMP(3),

    CONSTRAINT "SystemPromptVersion_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "SystemSetting" (
    "key" TEXT NOT NULL,
    "value" JSONB NOT NULL,
    "updatedById" TEXT NOT NULL,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "SystemSetting_pkey" PRIMARY KEY ("key")
);

CREATE TABLE "SystemAuditLog" (
    "id" TEXT NOT NULL,
    "actorId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "targetType" TEXT NOT NULL,
    "targetId" TEXT NOT NULL,
    "before" JSONB,
    "after" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SystemAuditLog_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "SystemPromptVersion_promptKey_version_key"
ON "SystemPromptVersion"("promptKey", "version");

CREATE INDEX "SystemPromptVersion_promptKey_status_idx"
ON "SystemPromptVersion"("promptKey", "status");

CREATE INDEX "SystemAuditLog_createdAt_idx"
ON "SystemAuditLog"("createdAt");

CREATE INDEX "SystemAuditLog_targetType_targetId_idx"
ON "SystemAuditLog"("targetType", "targetId");

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
    'system-analysis-prompt-v1',
    'analysis_system',
    '分析系统提示词',
    '控制分析任务的数据核验、报告生成和回复约束。',
    1,
    E'围绕用户提出的业务问题推进分析。\n- 涉及真实业务数据时，必须先查证，不能编造表、字段、指标、金额、占比或增长结论。\n- 报告只输出有据可查的数据和明确下一步建议。\n- 需要生成右侧交互式报告时，先用数据工具取得真实聚合数据，再调用 GenBI_report.create_interactive_report；不要把完整报告正文写在聊天回复中。\n- 输出中文。',
    'published',
    'system',
    CURRENT_TIMESTAMP
);
