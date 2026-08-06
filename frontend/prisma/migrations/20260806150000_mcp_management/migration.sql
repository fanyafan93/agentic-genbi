CREATE TABLE "McpServer" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "displayName" TEXT NOT NULL,
    "transport" TEXT NOT NULL,
    "config" JSONB NOT NULL,
    "encryptedSecrets" TEXT NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "createdById" TEXT NOT NULL,
    "updatedById" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "discoveredTools" JSONB NOT NULL DEFAULT '[]',
    "lastTestedAt" TIMESTAMP(3),
    "lastTestStatus" TEXT,
    "lastTestMessage" TEXT,

    CONSTRAINT "McpServer_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "McpServer_name_key" ON "McpServer"("name");
CREATE INDEX "McpServer_enabled_idx" ON "McpServer"("enabled");
