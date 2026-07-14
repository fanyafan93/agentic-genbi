CREATE TABLE sales_channel_monthly (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    month_start DATE NOT NULL,
    channel VARCHAR(64) NOT NULL,
    sales_amount DECIMAL(12, 2) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_sales_channel_monthly (month_start, channel)
);

INSERT INTO sales_channel_monthly (month_start, channel, sales_amount) VALUES
    ('2026-01-01', 'online', 120000.00),
    ('2026-01-01', 'store', 85000.00),
    ('2026-02-01', 'online', 132000.00),
    ('2026-02-01', 'store', 81000.00),
    ('2026-03-01', 'online', 128000.00),
    ('2026-03-01', 'store', 92000.00);

CREATE USER IF NOT EXISTS 'readonly_user'@'%' IDENTIFIED BY 'readonly-password';
GRANT SELECT ON analytics.* TO 'readonly_user'@'%';
