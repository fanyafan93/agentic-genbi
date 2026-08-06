ALTER TABLE reports
ADD COLUMN IF NOT EXISTS is_example BOOLEAN NOT NULL DEFAULT false;

UPDATE reports
SET is_example = true
WHERE deleted_at IS NULL
  AND title IN (
    '抖音订单简版示例',
    '抖音订单经营分析（复杂示例）',
    '抖音订单复杂表格（多筛选示例）',
    '抖音订单多栏经营看板（多筛选示例）',
    '抖音订单双区域独立筛选示例',
    '抖音订单表格能力示例',
    '抖音订单经营驾驶舱（图片布局模板）'
  );

UPDATE reports
SET deleted_at = COALESCE(deleted_at, now())
WHERE title = '代码示例：独立 Report';

CREATE INDEX IF NOT EXISTS idx_reports_example_updated
ON reports (updated_at DESC)
WHERE is_example = true AND deleted_at IS NULL;
