CREATE TABLE IF NOT EXISTS "report_builds" (
    "id" TEXT NOT NULL,
    "owner_id" TEXT NOT NULL,
    "session_id" TEXT NOT NULL,
    "turn_id" TEXT NOT NULL,
    "target_report_id" TEXT,
    "status" TEXT NOT NULL,
    "content" JSONB NOT NULL,
    "validation_errors" JSONB NOT NULL DEFAULT '[]'::jsonb,
    "revision" BIGINT NOT NULL DEFAULT 0,
    "published_report_id" TEXT,
    "last_successful_step" TEXT,
    "step_attempts" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expires_at" TIMESTAMPTZ NOT NULL,

    CONSTRAINT "report_builds_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "report_builds_session_id_fkey"
        FOREIGN KEY ("session_id")
        REFERENCES "analysis_threads"("id")
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "report_builds_turn_id_fkey"
        FOREIGN KEY ("turn_id")
        REFERENCES "analysis_turns"("id")
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "report_builds_target_report_id_fkey"
        FOREIGN KEY ("target_report_id")
        REFERENCES "reports"("id")
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT "report_builds_published_report_id_fkey"
        FOREIGN KEY ("published_report_id")
        REFERENCES "reports"("id")
        ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS "report_builds_session_id_updated_at_idx"
    ON "report_builds"("session_id", "updated_at" DESC);

CREATE INDEX IF NOT EXISTS "report_builds_turn_id_idx"
    ON "report_builds"("turn_id");

CREATE INDEX IF NOT EXISTS "report_builds_owner_id_status_updated_at_idx"
    ON "report_builds"("owner_id", "status", "updated_at" DESC);

CREATE INDEX IF NOT EXISTS "report_builds_expires_at_idx"
    ON "report_builds"("expires_at");
