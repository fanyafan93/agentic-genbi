CREATE TABLE "ModelConnection" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "displayName" TEXT NOT NULL,
    "providerType" TEXT NOT NULL,
    "model" TEXT NOT NULL,
    "baseUrl" TEXT NOT NULL,
    "encryptedApiKey" TEXT NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "isDefault" BOOLEAN NOT NULL DEFAULT false,
    "createdById" TEXT NOT NULL,
    "updatedById" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "lastTestedAt" TIMESTAMP(3),
    "lastTestStatus" TEXT,
    "lastTestMessage" TEXT,

    CONSTRAINT "ModelConnection_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "ModelConnection_name_key"
    ON "ModelConnection"("name");

CREATE INDEX "ModelConnection_enabled_idx"
    ON "ModelConnection"("enabled");

CREATE INDEX "ModelConnection_isDefault_idx"
    ON "ModelConnection"("isDefault");

CREATE UNIQUE INDEX "ModelConnection_one_default"
    ON "ModelConnection"("isDefault")
    WHERE "isDefault" = TRUE;

UPDATE "SystemSetting"
SET
    value = value - 'model',
    "updatedAt" = CURRENT_TIMESTAMP
WHERE key = 'runtime.policy'
  AND value ? 'model';
