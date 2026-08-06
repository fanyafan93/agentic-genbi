from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_START_DATE = "2026-07-05"
DEFAULT_END_DATE = "2026-08-03"
STATUS_VALUES = ["已关闭", "已发货", "已完成", "已支付", "待发货"]
TRAFFIC_VALUES = ["小店自卖", "未标记来源", "精选联盟"]
ALL_FIELD_COLUMNS = [
    ("sub_trade_no", "子订单号", 190),
    ("trade_no", "订单号", 190),
    ("ad_channel", "广告渠道", 150),
    ("app_channel", "App 渠道", 150),
    ("area", "区县", 140),
    ("cancel_reason", "取消原因", 240),
    ("city", "城市", 140),
    ("commitment_send_time", "承诺发货时间", 190),
    ("consignee", "收件人（脱敏）", 160),
    ("consignee_tel", "收件电话（脱敏）", 180),
    ("discount", "优惠金额", 140),
    ("express_infor", "快递信息", 240),
    ("finish_time", "完成时间", 190),
    ("freight", "运费", 120),
    ("handling_fees", "手续费", 130),
    ("is_channel_prod", "渠道商品", 130),
    ("merchant_discount", "商家优惠", 140),
    ("order_status", "订单状态", 140),
    ("order_time", "下单时间", 190),
    ("order_type", "订单类型", 140),
    ("path", "来源路径", 220),
    ("pay_amt", "支付金额", 140),
    ("pay_discounts", "支付优惠", 140),
    ("pay_method", "支付方式", 140),
    ("pay_time", "支付时间", 190),
    ("plaftform_discount", "平台优惠", 140),
    ("price_change", "改价金额", 140),
    ("product", "商品名称", 360),
    ("product_amt", "商品金额", 140),
    ("product_cnt", "商品数量", 140),
    ("product_code", "商品编码", 200),
    ("product_id", "商品 ID", 190),
    ("province", "省份", 140),
    ("real_merchant_discount", "实际商家优惠", 160),
    ("real_plaftform_discount", "实际平台优惠", 160),
    ("real_tlant_discount", "实际店铺优惠", 160),
    ("receiver_address", "收货地址（脱敏）", 280),
    ("red_envelope", "红包", 120),
    ("sales_state", "售后状态", 140),
    ("seller_no", "商家编码", 180),
    ("send_time", "发货时间", 190),
    ("street", "街道", 160),
    ("table_name", "来源文件", 180),
    ("tlant_discount", "店铺优惠", 140),
    ("tlant_id", "店铺 ID", 180),
    ("tlant_name", "店铺名称", 220),
    ("traffic_channel", "流量渠道", 150),
    ("traffic_genre", "流量体裁", 150),
    ("traffic_source", "流量来源", 150),
    ("traffic_type", "流量类型", 150),
    ("account", "账号", 180),
    ("update_time", "更新时间", 190),
    ("sync_time", "同步时间", 190),
]


def _select_options(values: list[str]) -> list[dict[str, str]]:
    return [{"label": value, "value": value} for value in values]


def _date_filter() -> dict[str, Any]:
    return {
        "date_range": {
            "type": "dateRange",
            "label": "下单日期",
            "defaultValue": [DEFAULT_START_DATE, DEFAULT_END_DATE],
        }
    }


def _date_parameters() -> dict[str, Any]:
    return {
        "start_date": {
            "filterId": "date_range",
            "type": "date",
            "valueIndex": 0,
        },
        "end_date": {
            "filterId": "date_range",
            "type": "date",
            "valueIndex": 1,
        },
    }


def _query(
    sql: str,
    *,
    pagination: bool = False,
    parameters: dict[str, Any] | None = None,
    sortable_fields: list[str] | None = None,
    filterable_fields: list[str] | None = None,
) -> dict[str, Any]:
    query = {
        "dataSource": "doris",
        "sql": sql.strip(),
        "parameters": (
            _date_parameters()
            if parameters is None
            else parameters
        ),
        "pagination": pagination,
    }
    if sortable_fields is not None or filterable_fields is not None:
        query["controls"] = {
            "sortableFields": sortable_fields or [],
            "filterableFields": filterable_fields or [],
        }
    return query


def _daily_trend_query() -> dict[str, Any]:
    return _query(
        """
        SELECT
          DATE_FORMAT(DATE(order_time), '%%Y-%%m-%%d') AS order_date,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0))
            / NULLIF(COUNT(DISTINCT trade_no), 0),
            2
          ) AS avg_order_value
        FROM ods.ods_dy_order
        WHERE order_time >= :start_date
          AND order_time < DATE_ADD(:end_date, INTERVAL 1 DAY)
        GROUP BY DATE(order_time)
        ORDER BY DATE(order_time)
        """,
        sortable_fields=[
            "order_date",
            "order_count",
            "pay_amount",
            "avg_order_value",
        ],
    )


def _base_layout(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "root": {"props": {}},
        "content": content,
        "zones": {},
    }


def build_simple_report() -> dict[str, Any]:
    return {
        "title": "抖音订单简版示例",
        "subtitle": "最近 30 个完整自然日的支付金额趋势与逐日明细",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "simple-note",
                        "content": (
                            "默认展示 2026-07-05 至 2026-08-03；"
                            "可修改日期范围并由后端重新查询。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "simple-filters",
                        "filterIds": ["date_range"],
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "simple-trend-title",
                        "title": "每日支付金额趋势",
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "simple-trend",
                        "chartId": "daily_pay_trend",
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "simple-table-title",
                        "title": "每日订单明细",
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "simple-table",
                        "tableId": "daily_summary",
                    },
                },
            ]
        ),
        "filters": _date_filter(),
        "charts": {
            "daily_pay_trend": {
                "queryId": "daily_trend",
                "option": {
                    "title": {"text": "每日支付金额（元）", "left": "center"},
                    "tooltip": {"trigger": "axis"},
                    "grid": {
                        "left": 72,
                        "right": 28,
                        "top": 64,
                        "bottom": 52,
                    },
                    "xAxis": {
                        "type": "category",
                        "axisLabel": {"rotate": 35},
                    },
                    "yAxis": {
                        "type": "value",
                        "name": "支付金额（元）",
                    },
                    "series": [
                        {
                            "type": "line",
                            "name": "支付金额",
                            "smooth": True,
                            "showSymbol": False,
                            "encode": {
                                "x": "order_date",
                                "y": "pay_amount",
                            },
                            "lineStyle": {"width": 3, "color": "#3b82f6"},
                            "areaStyle": {"opacity": 0.12},
                        }
                    ],
                },
            }
        },
        "tables": {
            "daily_summary": {
                "queryId": "daily_trend",
                "options": {
                    "columns": [
                        {
                            "field": "order_date",
                            "title": "日期",
                            "width": 130,
                            "sortable": True,
                        },
                        {
                            "field": "order_count",
                            "title": "订单数",
                            "width": 120,
                            "sortable": True,
                        },
                        {
                            "field": "pay_amount",
                            "title": "支付金额（元）",
                            "width": 160,
                            "sortable": True,
                        },
                        {
                            "field": "avg_order_value",
                            "title": "客单价（元）",
                            "width": 140,
                            "sortable": True,
                        },
                    ],
                    "widthMode": "standard",
                },
            }
        },
        "queries": {"daily_trend": _daily_trend_query()},
    }


def build_complex_report() -> dict[str, Any]:
    daily_query = _daily_trend_query()
    status_query = _query(
        """
        SELECT
          COALESCE(NULLIF(order_status, ''), '未标记状态') AS order_status,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount
        FROM ods.ods_dy_order
        WHERE order_time >= :start_date
          AND order_time < DATE_ADD(:end_date, INTERVAL 1 DAY)
        GROUP BY COALESCE(NULLIF(order_status, ''), '未标记状态')
        ORDER BY pay_amount DESC
        """
    )
    traffic_query = _query(
        """
        SELECT
          COALESCE(
            NULLIF(NULLIF(traffic_source, ''), '-'),
            '未标记来源'
          ) AS traffic_source,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount
        FROM ods.ods_dy_order
        WHERE order_time >= :start_date
          AND order_time < DATE_ADD(:end_date, INTERVAL 1 DAY)
        GROUP BY COALESCE(
          NULLIF(NULLIF(traffic_source, ''), '-'),
          '未标记来源'
        )
        ORDER BY pay_amount DESC
        """
    )
    shop_query = _query(
        """
        SELECT
          CASE
            WHEN COALESCE(NULLIF(tlant_name, ''), NULLIF(account, ''), '')
              LIKE '%%@%%'
            THEN '系统账号'
            ELSE COALESCE(
              NULLIF(tlant_name, ''),
              NULLIF(account, ''),
              '未标记店铺'
            )
          END AS shop_name,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0))
            / NULLIF(COUNT(DISTINCT trade_no), 0),
            2
          ) AS avg_order_value
        FROM ods.ods_dy_order
        WHERE order_time >= :start_date
          AND order_time < DATE_ADD(:end_date, INTERVAL 1 DAY)
        GROUP BY CASE
          WHEN COALESCE(NULLIF(tlant_name, ''), NULLIF(account, ''), '')
            LIKE '%%@%%'
          THEN '系统账号'
          ELSE COALESCE(
            NULLIF(tlant_name, ''),
            NULLIF(account, ''),
            '未标记店铺'
          )
        END
        ORDER BY pay_amount DESC
        LIMIT 10
        """
    )
    product_query = _query(
        """
        SELECT
          CAST(product_id AS CHAR) AS product_id,
          LEFT(
            COALESCE(NULLIF(product, ''), '未命名商品'),
            40
          ) AS product_name,
          COUNT(DISTINCT trade_no) AS order_count,
          SUM(
            COALESCE(CAST(NULLIF(product_cnt, '') AS DECIMAL(18, 2)), 0)
          ) AS product_quantity,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount
        FROM ods.ods_dy_order
        WHERE order_time >= :start_date
          AND order_time < DATE_ADD(:end_date, INTERVAL 1 DAY)
        GROUP BY
          CAST(product_id AS CHAR),
          LEFT(COALESCE(NULLIF(product, ''), '未命名商品'), 40)
        ORDER BY pay_amount DESC
        LIMIT 100
        """,
        pagination=True,
        sortable_fields=[
            "product_id",
            "product_name",
            "order_count",
            "product_quantity",
            "pay_amount",
        ],
    )
    return {
        "title": "抖音订单经营分析（复杂示例）",
        "subtitle": "趋势、订单状态、流量来源、店铺贡献与商品明细",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "complex-summary",
                        "content": (
                            "默认窗口为最近 30 个完整自然日（2026-07-05 至 "
                            "2026-08-03）。金额口径为 pay_amt 求和，订单口径为 "
                            "trade_no 去重；未展示收件人、电话或地址等个人信息。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "complex-filters",
                        "filterIds": ["date_range"],
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "complex-overview-title",
                        "title": "经营趋势",
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "complex-daily-chart",
                        "chartId": "daily_pay_trend",
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "complex-daily-table",
                        "tableId": "daily_summary",
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "complex-structure-title",
                        "title": "订单与流量结构",
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "complex-status-chart",
                        "chartId": "status_amount",
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "complex-traffic-chart",
                        "chartId": "traffic_amount",
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "complex-shop-title",
                        "title": "店铺与商品贡献",
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "complex-shop-chart",
                        "chartId": "shop_ranking",
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "complex-product-table",
                        "tableId": "product_ranking",
                    },
                },
            ]
        ),
        "filters": _date_filter(),
        "charts": {
            "daily_pay_trend": {
                "queryId": "daily_trend",
                "option": {
                    "title": {"text": "每日支付金额（元）", "left": "center"},
                    "tooltip": {"trigger": "axis"},
                    "grid": {
                        "left": 72,
                        "right": 28,
                        "top": 64,
                        "bottom": 52,
                    },
                    "xAxis": {
                        "type": "category",
                        "axisLabel": {"rotate": 35},
                    },
                    "yAxis": {
                        "type": "value",
                        "name": "支付金额（元）",
                    },
                    "series": [
                        {
                            "type": "line",
                            "name": "支付金额",
                            "smooth": True,
                            "showSymbol": False,
                            "encode": {
                                "x": "order_date",
                                "y": "pay_amount",
                            },
                            "lineStyle": {"width": 3, "color": "#2563eb"},
                            "areaStyle": {"opacity": 0.1},
                        }
                    ],
                },
            },
            "status_amount": {
                "queryId": "status_summary",
                "option": {
                    "title": {"text": "各订单状态支付金额", "left": "center"},
                    "tooltip": {"trigger": "axis"},
                    "grid": {
                        "left": 92,
                        "right": 36,
                        "top": 64,
                        "bottom": 36,
                    },
                    "xAxis": {
                        "type": "value",
                        "name": "支付金额（元）",
                    },
                    "yAxis": {"type": "category"},
                    "series": [
                        {
                            "type": "bar",
                            "name": "支付金额",
                            "encode": {
                                "x": "pay_amount",
                                "y": "order_status",
                            },
                            "itemStyle": {"color": "#6366f1"},
                        }
                    ],
                },
            },
            "traffic_amount": {
                "queryId": "traffic_summary",
                "option": {
                    "title": {"text": "流量来源支付金额占比", "left": "center"},
                    "tooltip": {"trigger": "item"},
                    "legend": {"bottom": 8},
                    "series": [
                        {
                            "type": "pie",
                            "name": "支付金额",
                            "radius": ["38%", "66%"],
                            "center": ["50%", "46%"],
                            "encode": {
                                "itemName": "traffic_source",
                                "value": "pay_amount",
                            },
                            "label": {
                                "formatter": "{b}: {d}%",
                            },
                        }
                    ],
                },
            },
            "shop_ranking": {
                "queryId": "shop_ranking",
                "option": {
                    "title": {"text": "Top 10 店铺支付金额", "left": "center"},
                    "tooltip": {"trigger": "axis"},
                    "grid": {
                        "left": 150,
                        "right": 36,
                        "top": 64,
                        "bottom": 36,
                    },
                    "xAxis": {
                        "type": "value",
                        "name": "支付金额（元）",
                    },
                    "yAxis": {
                        "type": "category",
                        "inverse": True,
                    },
                    "series": [
                        {
                            "type": "bar",
                            "name": "支付金额",
                            "encode": {
                                "x": "pay_amount",
                                "y": "shop_name",
                            },
                            "itemStyle": {"color": "#0f766e"},
                        }
                    ],
                },
            },
        },
        "tables": {
            "daily_summary": {
                "queryId": "daily_trend",
                "options": {
                    "columns": [
                        {
                            "field": "order_date",
                            "title": "日期",
                            "width": 130,
                            "sortable": True,
                        },
                        {
                            "field": "order_count",
                            "title": "订单数",
                            "width": 120,
                            "sortable": True,
                        },
                        {
                            "field": "pay_amount",
                            "title": "支付金额（元）",
                            "width": 160,
                            "sortable": True,
                        },
                        {
                            "field": "avg_order_value",
                            "title": "客单价（元）",
                            "width": 140,
                            "sortable": True,
                        },
                    ],
                    "widthMode": "standard",
                },
            },
            "product_ranking": {
                "queryId": "product_ranking",
                "options": {
                    "columns": [
                        {
                            "field": "product_id",
                            "title": "商品 ID",
                            "width": 190,
                            "sortable": True,
                        },
                        {
                            "field": "product_name",
                            "title": "商品名称（截取 40 字）",
                            "width": 360,
                            "sortable": True,
                        },
                        {
                            "field": "order_count",
                            "title": "订单数",
                            "width": 120,
                            "sortable": True,
                        },
                        {
                            "field": "product_quantity",
                            "title": "商品件数",
                            "width": 120,
                            "sortable": True,
                        },
                        {
                            "field": "pay_amount",
                            "title": "支付金额（元）",
                            "width": 160,
                            "sortable": True,
                        },
                    ],
                    "widthMode": "standard",
                },
            },
        },
        "queries": {
            "daily_trend": daily_query,
            "status_summary": status_query,
            "traffic_summary": traffic_query,
            "shop_ranking": shop_query,
            "product_ranking": product_query,
        },
    }


def _scoped_filter_definitions(
    date_filter_id: str,
    *,
    date_label: str,
    status_filter_id: str | None = None,
    status_label: str = "订单状态",
    traffic_filter_id: str | None = None,
    traffic_label: str = "流量来源",
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        date_filter_id: {
            "type": "dateRange",
            "label": date_label,
            "defaultValue": [DEFAULT_START_DATE, DEFAULT_END_DATE],
        }
    }
    if status_filter_id:
        filters[status_filter_id] = {
            "type": "multiSelect",
            "label": status_label,
            "defaultValue": STATUS_VALUES,
            "options": _select_options(STATUS_VALUES),
        }
    if traffic_filter_id:
        filters[traffic_filter_id] = {
            "type": "multiSelect",
            "label": traffic_label,
            "defaultValue": TRAFFIC_VALUES,
            "options": _select_options(TRAFFIC_VALUES),
        }
    return filters


def _scoped_parameters(
    date_filter_id: str,
    *,
    status_filter_id: str | None = None,
    traffic_filter_id: str | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "start_date": {
            "filterId": date_filter_id,
            "type": "date",
            "valueIndex": 0,
        },
        "end_date": {
            "filterId": date_filter_id,
            "type": "date",
            "valueIndex": 1,
        },
    }
    if status_filter_id:
        parameters["statuses"] = {
            "filterId": status_filter_id,
            "type": "string[]",
        }
    if traffic_filter_id:
        parameters["traffic_sources"] = {
            "filterId": traffic_filter_id,
            "type": "string[]",
        }
    return parameters


def _filter_sql(*, status: bool, traffic: bool) -> str:
    clauses = [
        "order_time >= :start_date",
        "order_time < DATE_ADD(:end_date, INTERVAL 1 DAY)",
    ]
    if status:
        clauses.append(
            "COALESCE(NULLIF(order_status, ''), '未标记状态') "
            "IN (:statuses)"
        )
    if traffic:
        clauses.append(
            "COALESCE(NULLIF(NULLIF(traffic_source, ''), '-'), "
            "'未标记来源') IN (:traffic_sources)"
        )
    return "\n          AND ".join(clauses)


def _filtered_daily_query(
    parameters: dict[str, Any],
    *,
    status: bool,
    traffic: bool,
    pagination: bool,
) -> dict[str, Any]:
    return _query(
        f"""
        SELECT
          DATE_FORMAT(DATE(order_time), '%%Y-%%m-%%d') AS order_date,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0))
            / NULLIF(COUNT(DISTINCT trade_no), 0),
            2
          ) AS avg_order_value
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=status, traffic=traffic)}
        GROUP BY DATE(order_time)
        ORDER BY DATE(order_time)
        """,
        parameters=parameters,
        pagination=pagination,
        sortable_fields=[
            "order_date",
            "order_count",
            "pay_amount",
            "avg_order_value",
        ],
    )


def _filtered_status_query(
    parameters: dict[str, Any],
    *,
    status: bool,
    traffic: bool,
) -> dict[str, Any]:
    return _query(
        f"""
        SELECT
          COALESCE(NULLIF(order_status, ''), '未标记状态') AS order_status,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=status, traffic=traffic)}
        GROUP BY COALESCE(NULLIF(order_status, ''), '未标记状态')
        ORDER BY pay_amount DESC
        """,
        parameters=parameters,
        sortable_fields=["order_status", "order_count", "pay_amount"],
        filterable_fields=["order_status"],
    )


def _filtered_traffic_query(
    parameters: dict[str, Any],
    *,
    status: bool,
    traffic: bool,
) -> dict[str, Any]:
    return _query(
        f"""
        SELECT
          COALESCE(
            NULLIF(NULLIF(traffic_source, ''), '-'),
            '未标记来源'
          ) AS traffic_source,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=status, traffic=traffic)}
        GROUP BY COALESCE(
          NULLIF(NULLIF(traffic_source, ''), '-'),
          '未标记来源'
        )
        ORDER BY pay_amount DESC
        """,
        parameters=parameters,
        sortable_fields=["traffic_source", "order_count", "pay_amount"],
        filterable_fields=["traffic_source"],
    )


def _filtered_shop_query(
    parameters: dict[str, Any],
    *,
    status: bool,
    traffic: bool,
    pagination: bool,
) -> dict[str, Any]:
    return _query(
        f"""
        SELECT
          CASE
            WHEN COALESCE(NULLIF(tlant_name, ''), NULLIF(account, ''), '')
              LIKE '%%@%%'
            THEN '系统账号'
            ELSE COALESCE(
              NULLIF(tlant_name, ''),
              NULLIF(account, ''),
              '未标记店铺'
            )
          END AS shop_name,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0))
            / NULLIF(COUNT(DISTINCT trade_no), 0),
            2
          ) AS avg_order_value
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=status, traffic=traffic)}
        GROUP BY CASE
          WHEN COALESCE(NULLIF(tlant_name, ''), NULLIF(account, ''), '')
            LIKE '%%@%%'
          THEN '系统账号'
          ELSE COALESCE(
            NULLIF(tlant_name, ''),
            NULLIF(account, ''),
            '未标记店铺'
          )
        END
        ORDER BY pay_amount DESC
        LIMIT 100
        """,
        parameters=parameters,
        pagination=pagination,
        sortable_fields=[
            "shop_name",
            "order_count",
            "pay_amount",
            "avg_order_value",
        ],
    )


def _daily_columns() -> list[dict[str, Any]]:
    return [
        {
            "field": "order_date",
            "title": "日期",
            "width": 150,
            "sortable": True,
        },
        {
            "field": "order_count",
            "title": "订单数",
            "width": 140,
            "sortable": True,
        },
        {
            "field": "pay_amount",
            "title": "支付金额（元）",
            "width": 180,
            "sortable": True,
        },
        {
            "field": "avg_order_value",
            "title": "客单价（元）",
            "width": 160,
            "sortable": True,
        },
    ]


def _shop_columns() -> list[dict[str, Any]]:
    return [
        {
            "field": "shop_name",
            "title": "店铺",
            "width": 240,
            "sortable": True,
        },
        {
            "field": "order_count",
            "title": "订单数",
            "width": 140,
            "sortable": True,
        },
        {
            "field": "pay_amount",
            "title": "支付金额（元）",
            "width": 180,
            "sortable": True,
        },
        {
            "field": "avg_order_value",
            "title": "客单价（元）",
            "width": 160,
            "sortable": True,
        },
    ]


def _line_chart(title: str) -> dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 66, "right": 24, "top": 62, "bottom": 52},
        "xAxis": {"type": "category", "axisLabel": {"rotate": 32}},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": "支付金额",
                "smooth": True,
                "showSymbol": False,
                "encode": {"x": "order_date", "y": "pay_amount"},
                "lineStyle": {"width": 3, "color": "#2563eb"},
                "areaStyle": {"opacity": 0.1},
            }
        ],
    }


def _bar_chart(
    title: str,
    category_field: str,
    color: str,
) -> dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 104, "right": 24, "top": 62, "bottom": 36},
        "xAxis": {
            "type": "value",
            "splitNumber": 3,
            "axisLabel": {"fontSize": 10, "hideOverlap": True},
        },
        "yAxis": {"type": "category", "inverse": True},
        "series": [
            {
                "type": "bar",
                "name": "支付金额",
                "encode": {"x": "pay_amount", "y": category_field},
                "itemStyle": {"color": color},
            }
        ],
    }


def _pie_chart(title: str) -> dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 8},
        "series": [
            {
                "type": "pie",
                "name": "支付金额",
                "radius": ["38%", "66%"],
                "center": ["50%", "46%"],
                "encode": {
                    "itemName": "traffic_source",
                    "value": "pay_amount",
                },
                "label": {"formatter": "{b}: {d}%"},
            }
        ],
    }


def build_complex_table_report() -> dict[str, Any]:
    filters = _scoped_filter_definitions(
        "date_range",
        date_label="下单日期",
        status_filter_id="statuses",
        traffic_filter_id="traffic_sources",
    )
    parameters = _scoped_parameters(
        "date_range",
        status_filter_id="statuses",
        traffic_filter_id="traffic_sources",
    )
    query = _query(
        f"""
        SELECT
          DATE_FORMAT(order_time, '%%Y-%%m-%%d %%H:%%i:%%s') AS order_date,
          CAST(trade_no AS CHAR) AS trade_no,
          COALESCE(NULLIF(order_status, ''), '未标记状态') AS order_status,
          COALESCE(
            NULLIF(NULLIF(traffic_source, ''), '-'),
            '未标记来源'
          ) AS traffic_source,
          CASE
            WHEN COALESCE(NULLIF(tlant_name, ''), NULLIF(account, ''), '')
              LIKE '%%@%%'
            THEN '系统账号'
            ELSE COALESCE(
              NULLIF(tlant_name, ''),
              NULLIF(account, ''),
              '未标记店铺'
            )
          END AS shop_name,
          CAST(product_id AS CHAR) AS product_id,
          LEFT(COALESCE(NULLIF(product, ''), '未命名商品'), 50)
            AS product_name,
          COALESCE(CAST(NULLIF(product_cnt, '') AS DECIMAL(18, 2)), 0)
            AS product_quantity,
          ROUND(
            COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0),
            2
          ) AS pay_amount
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=True, traffic=True)}
        ORDER BY order_time DESC
        LIMIT 500
        """,
        parameters=parameters,
        pagination=True,
        sortable_fields=[
            "order_date",
            "trade_no",
            "shop_name",
            "product_id",
            "product_quantity",
            "pay_amount",
        ],
        filterable_fields=["order_status", "traffic_source"],
    )
    columns = [
        {
            "field": "order_date",
            "title": "下单时间",
            "width": 190,
            "sortable": True,
        },
        {
            "field": "trade_no",
            "title": "订单号",
            "width": 220,
            "sortable": True,
        },
        {
            "field": "order_status",
            "title": "订单状态",
            "width": 140,
            "filterOptions": _select_options(STATUS_VALUES),
        },
        {
            "field": "traffic_source",
            "title": "流量来源",
            "width": 150,
            "filterOptions": _select_options(TRAFFIC_VALUES),
        },
        {
            "field": "shop_name",
            "title": "店铺",
            "width": 220,
            "sortable": True,
        },
        {
            "field": "product_id",
            "title": "商品 ID",
            "width": 190,
            "sortable": True,
        },
        {
            "field": "product_name",
            "title": "商品名称",
            "width": 360,
        },
        {
            "field": "product_quantity",
            "title": "商品件数",
            "width": 140,
            "sortable": True,
        },
        {
            "field": "pay_amount",
            "title": "支付金额（元）",
            "width": 170,
            "sortable": True,
        },
    ]
    return {
        "title": "抖音订单复杂表格（多筛选示例）",
        "subtitle": "多条件查询、列头排序筛选、分页与双向滚动",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "complex-table-note",
                        "content": (
                            "日期、订单状态和流量来源共同控制明细；"
                            "表头可排序或按状态、来源筛选。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "complex-table-filters",
                        "filterIds": [
                            "date_range",
                            "statuses",
                            "traffic_sources",
                        ],
                        "columnSpan": 12,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "complex-order-detail",
                        "tableId": "order_detail",
                        "columnSpan": 12,
                    },
                },
            ]
        ),
        "filters": filters,
        "charts": {},
        "tables": {
            "order_detail": {
                "queryId": "order_detail",
                "options": {
                    "columns": columns,
                    "widthMode": "standard",
                },
            }
        },
        "queries": {"order_detail": query},
    }


def build_multi_column_report() -> dict[str, Any]:
    filters = _scoped_filter_definitions(
        "date_range",
        date_label="下单日期",
        status_filter_id="statuses",
        traffic_filter_id="traffic_sources",
    )
    parameters = _scoped_parameters(
        "date_range",
        status_filter_id="statuses",
        traffic_filter_id="traffic_sources",
    )
    daily = _filtered_daily_query(
        parameters,
        status=True,
        traffic=True,
        pagination=True,
    )
    status = _filtered_status_query(
        parameters,
        status=True,
        traffic=True,
    )
    traffic = _filtered_traffic_query(
        parameters,
        status=True,
        traffic=True,
    )
    shop = _filtered_shop_query(
        parameters,
        status=True,
        traffic=True,
        pagination=True,
    )
    return {
        "title": "抖音订单多栏经营看板（多筛选示例）",
        "subtitle": "十二栏布局中的三列图表、两列表格与联动筛选",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "multi-column-note",
                        "content": (
                            "同一组日期、状态和流量筛选控制下方所有内容；"
                            "图表采用三列布局，表格采用两列布局。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "multi-column-filters",
                        "filterIds": [
                            "date_range",
                            "statuses",
                            "traffic_sources",
                        ],
                        "columnSpan": 12,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "multi-daily",
                        "chartId": "daily",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "multi-status",
                        "chartId": "status",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "multi-traffic",
                        "chartId": "traffic",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "multi-daily-table",
                        "tableId": "daily",
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "multi-shop-table",
                        "tableId": "shop",
                        "columnSpan": 6,
                    },
                },
            ]
        ),
        "filters": filters,
        "charts": {
            "daily": {
                "queryId": "daily",
                "option": _line_chart("每日支付金额"),
            },
            "status": {
                "queryId": "status",
                "option": _bar_chart(
                    "订单状态",
                    "order_status",
                    "#6366f1",
                ),
            },
            "traffic": {
                "queryId": "traffic",
                "option": _pie_chart("流量来源"),
            },
        },
        "tables": {
            "daily": {
                "queryId": "daily",
                "options": {
                    "columns": _daily_columns(),
                    "widthMode": "standard",
                },
            },
            "shop": {
                "queryId": "shop",
                "options": {
                    "columns": _shop_columns(),
                    "widthMode": "standard",
                },
            },
        },
        "queries": {
            "daily": daily,
            "status": status,
            "traffic": traffic,
            "shop": shop,
        },
    }


def build_independent_filters_report() -> dict[str, Any]:
    filters = {
        **_scoped_filter_definitions(
            "left_date_range",
            date_label="趋势日期",
            status_filter_id="left_statuses",
            status_label="趋势订单状态",
        ),
        **_scoped_filter_definitions(
            "right_date_range",
            date_label="结构日期",
            traffic_filter_id="right_traffic_sources",
            traffic_label="结构流量来源",
        ),
    }
    left_parameters = _scoped_parameters(
        "left_date_range",
        status_filter_id="left_statuses",
    )
    right_parameters = _scoped_parameters(
        "right_date_range",
        traffic_filter_id="right_traffic_sources",
    )
    left_daily = _filtered_daily_query(
        left_parameters,
        status=True,
        traffic=False,
        pagination=True,
    )
    left_status = _filtered_status_query(
        left_parameters,
        status=True,
        traffic=False,
    )
    right_traffic = _filtered_traffic_query(
        right_parameters,
        status=False,
        traffic=True,
    )
    right_shop = _filtered_shop_query(
        right_parameters,
        status=False,
        traffic=True,
        pagination=True,
    )
    return {
        "title": "抖音订单双区域独立筛选示例",
        "subtitle": "左右两组筛选分别控制各自图表和表格",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "independent-note",
                        "content": (
                            "左侧趋势筛选只刷新左侧内容；"
                            "右侧结构筛选只刷新右侧内容。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "left-filters",
                        "filterIds": [
                            "left_date_range",
                            "left_statuses",
                        ],
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "right-filters",
                        "filterIds": [
                            "right_date_range",
                            "right_traffic_sources",
                        ],
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "left-status-chart",
                        "chartId": "left_status",
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "right-traffic-chart",
                        "chartId": "right_traffic",
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "left-daily-table",
                        "tableId": "left_daily",
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "right-shop-table",
                        "tableId": "right_shop",
                        "columnSpan": 6,
                    },
                },
            ]
        ),
        "filters": filters,
        "charts": {
            "left_status": {
                "queryId": "left_status",
                "option": _bar_chart(
                    "左侧：订单状态",
                    "order_status",
                    "#2563eb",
                ),
            },
            "right_traffic": {
                "queryId": "right_traffic",
                "option": _pie_chart("右侧：流量来源"),
            },
        },
        "tables": {
            "left_daily": {
                "queryId": "left_daily",
                "options": {
                    "columns": _daily_columns(),
                    "widthMode": "standard",
                },
            },
            "right_shop": {
                "queryId": "right_shop",
                "options": {
                    "columns": _shop_columns(),
                    "widthMode": "standard",
                },
            },
        },
        "queries": {
            "left_daily": left_daily,
            "left_status": left_status,
            "right_traffic": right_traffic,
            "right_shop": right_shop,
        },
    }


def _grouped_order_query(
    parameters: dict[str, Any],
    *,
    status: bool = True,
    traffic: bool = True,
) -> dict[str, Any]:
    return _query(
        f"""
        SELECT
          COALESCE(
            NULLIF(NULLIF(traffic_source, ''), '-'),
            '未标记来源'
          ) AS traffic_source,
          CASE
            WHEN COALESCE(NULLIF(tlant_name, ''), NULLIF(account, ''), '')
              LIKE '%%@%%'
            THEN '系统账号'
            ELSE COALESCE(
              NULLIF(tlant_name, ''),
              NULLIF(account, ''),
              '未标记店铺'
            )
          END AS shop_name,
          COALESCE(NULLIF(order_status, ''), '未标记状态')
            AS order_status,
          COUNT(DISTINCT trade_no) AS order_count,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)),
            2
          ) AS pay_amount,
          ROUND(
            SUM(COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0))
            / NULLIF(COUNT(DISTINCT trade_no), 0),
            2
          ) AS avg_order_value
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=status, traffic=traffic)}
        GROUP BY 1, 2, 3
        ORDER BY traffic_source, shop_name, pay_amount DESC
        LIMIT 120
        """,
        parameters=parameters,
        sortable_fields=[
            "traffic_source",
            "shop_name",
            "order_status",
            "order_count",
            "pay_amount",
            "avg_order_value",
        ],
        filterable_fields=["order_status", "traffic_source"],
    )


def _grouped_table_options() -> dict[str, Any]:
    return {
        "height": 430,
        "columns": [
            {
                "field": "traffic_source",
                "title": "流量来源",
                "width": 170,
                "filterOptions": _select_options(TRAFFIC_VALUES),
            },
            {
                "field": "shop_name",
                "title": "店铺",
                "width": 220,
                "sortable": True,
            },
            {
                "field": "order_status",
                "title": "订单状态",
                "width": 140,
                "filterOptions": _select_options(STATUS_VALUES),
            },
            {
                "field": "order_count",
                "title": "订单数",
                "width": 130,
                "sortable": True,
            },
            {
                "field": "pay_amount",
                "title": "支付金额（元）",
                "width": 170,
                "sortable": True,
            },
            {
                "field": "avg_order_value",
                "title": "客单价（元）",
                "width": 150,
                "sortable": True,
            },
        ],
        "groupBy": ["traffic_source", "shop_name"],
        "widthMode": "standard",
    }


def _pivot_table_options() -> dict[str, Any]:
    return {
        "height": 430,
        "rows": [
            {
                "dimensionKey": "traffic_source",
                "title": "流量来源",
                "width": 180,
            },
            {
                "dimensionKey": "shop_name",
                "title": "店铺",
                "width": 220,
            },
        ],
        "columns": [
            {
                "dimensionKey": "order_status",
                "title": "订单状态",
            }
        ],
        "indicators": [
            {
                "indicatorKey": "order_count",
                "title": "订单数",
                "width": 110,
            },
            {
                "indicatorKey": "pay_amount",
                "title": "支付金额",
                "width": 140,
            },
        ],
        "indicatorsAsCol": True,
        "rowHierarchyType": "tree",
        "rowExpandLevel": 2,
        "rowHierarchyIndent": 18,
        "dataConfig": {
            "totals": {
                "row": {
                    "showGrandTotals": True,
                    "showSubTotals": True,
                    "showSubTotalsOnTreeNode": True,
                    "grandTotalLabel": "总计",
                    "subTotalLabel": "小计",
                },
                "column": {
                    "showGrandTotals": True,
                    "showSubTotals": False,
                    "grandTotalLabel": "总计",
                },
            }
        },
        "widthMode": "standard",
    }


def _all_fields_query(
    parameters: dict[str, Any],
) -> dict[str, Any]:
    masked_fields = {
        "consignee": (
            "CASE WHEN NULLIF(consignee, '') IS NULL THEN '' "
            "ELSE CONCAT(LEFT(consignee, 1), '**') END AS consignee"
        ),
        "consignee_tel": (
            "CASE WHEN NULLIF(consignee_tel, '') IS NULL THEN '' "
            "ELSE CONCAT(LEFT(consignee_tel, 3), '****', "
            "RIGHT(consignee_tel, 4)) END AS consignee_tel"
        ),
        "receiver_address": (
            "CASE WHEN NULLIF(receiver_address, '') IS NULL THEN '' "
            "ELSE CONCAT(LEFT(receiver_address, 8), '***') "
            "END AS receiver_address"
        ),
    }
    select_fields = [
        masked_fields.get(field, field)
        for field, _title, _width in ALL_FIELD_COLUMNS
    ]
    return _query(
        f"""
        SELECT
          {",\n          ".join(select_fields)}
        FROM ods.ods_dy_order
        WHERE {_filter_sql(status=True, traffic=True)}
        ORDER BY order_time DESC
        LIMIT 1000
        """,
        parameters=parameters,
        pagination=True,
        sortable_fields=[
            "sub_trade_no",
            "trade_no",
            "order_time",
            "pay_time",
            "pay_amt",
            "product_cnt",
            "product_id",
            "update_time",
        ],
        filterable_fields=["order_status", "traffic_source"],
    )


def _all_fields_table_options() -> dict[str, Any]:
    sortable = {
        "sub_trade_no",
        "trade_no",
        "order_time",
        "pay_time",
        "pay_amt",
        "product_cnt",
        "product_id",
        "update_time",
    }
    filter_options = {
        "order_status": _select_options(STATUS_VALUES),
        "traffic_source": _select_options(TRAFFIC_VALUES),
    }
    return {
        "height": 520,
        "columns": [
            {
                "field": field,
                "title": title,
                "width": width,
                **({"sortable": True} if field in sortable else {}),
                **(
                    {"filterOptions": filter_options[field]}
                    if field in filter_options
                    else {}
                ),
            }
            for field, title, width in ALL_FIELD_COLUMNS
        ],
        "frozenColCount": 2,
        "widthMode": "standard",
    }


def build_table_showcase_report() -> dict[str, Any]:
    filters = _scoped_filter_definitions(
        "date_range",
        date_label="下单日期",
        status_filter_id="statuses",
        traffic_filter_id="traffic_sources",
    )
    parameters = _scoped_parameters(
        "date_range",
        status_filter_id="statuses",
        traffic_filter_id="traffic_sources",
    )
    return {
        "title": "抖音订单表格能力示例",
        "subtitle": "层级分组、透视交叉、53 字段宽表与后端分页",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "table-showcase-note",
                        "content": (
                            "上方左右两栏分别展示可展开分组表和透视交叉表；"
                            "下方宽表展开源表全部 53 个字段。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "table-showcase-filters",
                        "filterIds": [
                            "date_range",
                            "statuses",
                            "traffic_sources",
                        ],
                        "columnSpan": 12,
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "complex-tables-title",
                        "title": "复杂表结构",
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "traffic-shop-group",
                        "tableId": "traffic_shop_group",
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "status-traffic-pivot",
                        "tableId": "status_traffic_pivot",
                        "columnSpan": 6,
                    },
                },
                {
                    "type": "SectionBlock",
                    "props": {
                        "id": "all-fields-title",
                        "title": "全部字段宽表",
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "all-fields-table",
                        "tableId": "all_fields",
                        "columnSpan": 12,
                    },
                },
            ]
        ),
        "filters": filters,
        "charts": {},
        "tables": {
            "traffic_shop_group": {
                "queryId": "group_summary",
                "options": _grouped_table_options(),
            },
            "status_traffic_pivot": {
                "type": "pivot",
                "queryId": "group_summary",
                "options": _pivot_table_options(),
            },
            "all_fields": {
                "type": "list",
                "queryId": "all_fields",
                "exportColumns": [
                    {"field": "sub_trade_no", "title": "子订单号", "type": "text"},
                    {"field": "trade_no", "title": "订单号", "type": "text"},
                    {"field": "order_time", "title": "下单时间", "type": "datetime"},
                    {"field": "order_status", "title": "订单状态", "type": "text"},
                    {"field": "product", "title": "商品名称", "type": "text"},
                    {"field": "product_id", "title": "商品 ID", "type": "text"},
                    {"field": "product_cnt", "title": "商品数量", "type": "number"},
                    {"field": "pay_amt", "title": "支付金额", "type": "number"},
                    {"field": "traffic_source", "title": "流量来源", "type": "text"},
                    {"field": "tlant_name", "title": "店铺名称", "type": "text"},
                ],
                "options": _all_fields_table_options(),
            },
        },
        "queries": {
            "group_summary": _grouped_order_query(parameters),
            "all_fields": _all_fields_query(parameters),
        },
    }


def _image_layout_queries(
    parameters: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    filter_sql = _filter_sql(status=False, traffic=False)
    pay_amount = (
        "COALESCE(CAST(NULLIF(pay_amt, '') AS DECIMAL(18, 2)), 0)"
    )
    return {
        "weekday_radar": _query(
            f"""
            SELECT
              '订单数' AS metric,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 2
                THEN trade_no END) AS monday,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 3
                THEN trade_no END) AS tuesday,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 4
                THEN trade_no END) AS wednesday,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 5
                THEN trade_no END) AS thursday,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 6
                THEN trade_no END) AS friday,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 7
                THEN trade_no END) AS saturday,
              COUNT(DISTINCT CASE WHEN DAYOFWEEK(order_time) = 1
                THEN trade_no END) AS sunday
            FROM ods.ods_dy_order
            WHERE {filter_sql}
            """,
            parameters=parameters,
        ),
        "daily_combo": _query(
            f"""
            SELECT
              DATE_FORMAT(DATE(order_time), '%%m-%%d') AS order_date,
              COUNT(DISTINCT trade_no) AS order_count,
              ROUND(SUM({pay_amount}), 2) AS pay_amount
            FROM ods.ods_dy_order
            WHERE {filter_sql}
            GROUP BY DATE(order_time)
            ORDER BY DATE(order_time)
            """,
            parameters=parameters,
        ),
        "channel_composition": _query(
            f"""
            SELECT
              COALESCE(
                NULLIF(NULLIF(traffic_source, ''), '-'),
                '未标记来源'
              ) AS traffic_source,
              COUNT(DISTINCT CASE WHEN order_status = '已支付'
                THEN trade_no END) AS paid_count,
              COUNT(DISTINCT CASE WHEN order_status = '待发货'
                THEN trade_no END) AS pending_count,
              COUNT(DISTINCT CASE WHEN order_status = '已发货'
                THEN trade_no END) AS shipped_count,
              COUNT(DISTINCT CASE WHEN order_status = '已完成'
                THEN trade_no END) AS completed_count
            FROM ods.ods_dy_order
            WHERE {filter_sql}
            GROUP BY 1
            ORDER BY (
              paid_count + pending_count + shipped_count + completed_count
            ) DESC
            """,
            parameters=parameters,
        ),
        "fulfillment_rate": _query(
            f"""
            SELECT
              '履约订单占比' AS metric,
              ROUND(
                COUNT(DISTINCT CASE
                  WHEN order_status IN ('已发货', '已完成')
                  THEN trade_no
                END)
                * 100.0
                / NULLIF(COUNT(DISTINCT trade_no), 0),
                2
              ) AS fulfillment_rate
            FROM ods.ods_dy_order
            WHERE {filter_sql}
            """,
            parameters=parameters,
        ),
        "status_funnel": _query(
            f"""
            SELECT
              COALESCE(NULLIF(order_status, ''), '未标记状态') AS stage,
              COUNT(DISTINCT trade_no) AS order_count
            FROM ods.ods_dy_order
            WHERE {filter_sql}
            GROUP BY 1
            ORDER BY order_count DESC
            """,
            parameters=parameters,
        ),
    }


def _image_layout_charts() -> dict[str, Any]:
    return {
        "weekday_radar": {
            "queryId": "weekday_radar",
            "option": {
                "title": {"text": "星期订单雷达图", "left": 8, "top": 8},
                "tooltip": {"trigger": "item"},
                "radar": {
                    "center": ["50%", "56%"],
                    "radius": "62%",
                    "splitNumber": 4,
                    "indicator": [
                        {"name": "周一", "max": 100000},
                        {"name": "周二", "max": 100000},
                        {"name": "周三", "max": 100000},
                        {"name": "周四", "max": 100000},
                        {"name": "周五", "max": 100000},
                        {"name": "周六", "max": 100000},
                        {"name": "周日", "max": 100000},
                    ],
                },
                "series": [
                    {
                        "type": "radar",
                        "name": "订单数",
                        "encode": {
                            "itemName": "metric",
                            "indicator_0": "monday",
                            "indicator_1": "tuesday",
                            "indicator_2": "wednesday",
                            "indicator_3": "thursday",
                            "indicator_4": "friday",
                            "indicator_5": "saturday",
                            "indicator_6": "sunday",
                        },
                        "areaStyle": {"color": "#60a5fa", "opacity": 0.34},
                        "lineStyle": {"color": "#2563eb", "width": 2},
                        "itemStyle": {"color": "#2563eb"},
                    }
                ],
            },
        },
        "daily_combo": {
            "queryId": "daily_combo",
            "option": {
                "title": {"text": "每日销量与支付金额", "left": 8, "top": 8},
                "tooltip": {"trigger": "axis"},
                "legend": {"top": 10, "right": 12},
                "grid": {"left": 58, "right": 58, "top": 58, "bottom": 42},
                "xAxis": {"type": "category"},
                "yAxis": [
                    {"type": "value", "name": "支付金额"},
                    {"type": "value", "name": "订单数"},
                ],
                "series": [
                    {
                        "type": "bar",
                        "name": "支付金额",
                        "encode": {"x": "order_date", "y": "pay_amount"},
                        "itemStyle": {"color": "#60a5fa"},
                        "barMaxWidth": 22,
                    },
                    {
                        "type": "line",
                        "name": "订单数",
                        "yAxisIndex": 1,
                        "smooth": True,
                        "showSymbol": False,
                        "encode": {"x": "order_date", "y": "order_count"},
                        "lineStyle": {"color": "#f59e0b", "width": 2},
                        "areaStyle": {"color": "#fde68a", "opacity": 0.22},
                    },
                ],
            },
        },
        "channel_composition": {
            "queryId": "channel_composition",
            "option": {
                "title": {"text": "渠道订单状态构成", "left": 8, "top": 8},
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "legend": {"bottom": 4},
                "grid": {"left": 88, "right": 18, "top": 48, "bottom": 58},
                "xAxis": {"type": "value"},
                "yAxis": {"type": "category"},
                "series": [
                    {
                        "type": "bar",
                        "name": "已支付",
                        "stack": "status",
                        "encode": {"x": "paid_count", "y": "traffic_source"},
                        "itemStyle": {"color": "#3b82f6"},
                    },
                    {
                        "type": "bar",
                        "name": "待发货",
                        "stack": "status",
                        "encode": {"x": "pending_count", "y": "traffic_source"},
                        "itemStyle": {"color": "#34d399"},
                    },
                    {
                        "type": "bar",
                        "name": "已发货",
                        "stack": "status",
                        "encode": {"x": "shipped_count", "y": "traffic_source"},
                        "itemStyle": {"color": "#93c5fd"},
                    },
                    {
                        "type": "bar",
                        "name": "已完成",
                        "stack": "status",
                        "encode": {"x": "completed_count", "y": "traffic_source"},
                        "itemStyle": {"color": "#fbbf24"},
                    },
                ],
            },
        },
        "fulfillment_rate": {
            "queryId": "fulfillment_rate",
            "option": {
                "title": {"text": "履约订单占比", "left": 8, "top": 8},
                "tooltip": {"formatter": "{b}: {c}%"},
                "series": [
                    {
                        "type": "gauge",
                        "name": "履约订单占比",
                        "center": ["50%", "58%"],
                        "radius": "78%",
                        "startAngle": 210,
                        "endAngle": -30,
                        "min": 0,
                        "max": 100,
                        "progress": {
                            "show": True,
                            "width": 13,
                            "itemStyle": {"color": "#38bdf8"},
                        },
                        "axisLine": {"lineStyle": {"width": 13}},
                        "pointer": {"show": False},
                        "axisTick": {"show": False},
                        "splitLine": {"show": False},
                        "axisLabel": {"distance": -26, "fontSize": 9},
                        "detail": {
                            "valueAnimation": True,
                            "formatter": "{value}%",
                            "fontSize": 24,
                            "offsetCenter": [0, "8%"],
                            "color": "#1e3a5f",
                        },
                        "encode": {
                            "value": "fulfillment_rate",
                            "itemName": "metric",
                        },
                    }
                ],
            },
        },
        "status_funnel": {
            "queryId": "status_funnel",
            "option": {
                "title": {"text": "订单状态漏斗", "left": 8, "top": 8},
                "tooltip": {"trigger": "item"},
                "legend": {"bottom": 4},
                "color": ["#3b82f6", "#34d399", "#93c5fd", "#fbbf24", "#fb7185"],
                "series": [
                    {
                        "type": "funnel",
                        "name": "订单数",
                        "left": "12%",
                        "top": 52,
                        "bottom": 42,
                        "width": "76%",
                        "sort": "descending",
                        "gap": 2,
                        "encode": {
                            "itemName": "stage",
                            "value": "order_count",
                        },
                        "label": {"show": True, "position": "inside"},
                    }
                ],
            },
        },
    }


def build_image_layout_report() -> dict[str, Any]:
    filters = _date_filter()
    parameters = _date_parameters()
    queries = _image_layout_queries(parameters)
    queries["department_summary"] = _grouped_order_query(
        parameters,
        status=False,
        traffic=False,
    )
    return {
        "title": "抖音订单经营驾驶舱（图片布局模板）",
        "subtitle": "参照图片的 4+8、4+4+4、12 栏经营看板",
        "layout": _base_layout(
            [
                {
                    "type": "MarkdownBlock",
                    "props": {
                        "id": "image-template-note",
                        "content": (
                            "模板按十二栏栅格排列：首行雷达图与组合图，"
                            "次行三张结构图，底部为可展开层级汇总表。"
                        ),
                    },
                },
                {
                    "type": "FilterBlock",
                    "props": {
                        "id": "image-template-filter",
                        "filterIds": ["date_range"],
                        "columnSpan": 12,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "weekday-radar",
                        "chartId": "weekday_radar",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "daily-combo",
                        "chartId": "daily_combo",
                        "columnSpan": 8,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "channel-composition",
                        "chartId": "channel_composition",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "fulfillment-rate",
                        "chartId": "fulfillment_rate",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": "status-funnel",
                        "chartId": "status_funnel",
                        "columnSpan": 4,
                    },
                },
                {
                    "type": "TableBlock",
                    "props": {
                        "id": "department-summary",
                        "tableId": "department_summary",
                        "columnSpan": 12,
                    },
                },
            ]
        ),
        "filters": filters,
        "charts": _image_layout_charts(),
        "tables": {
            "department_summary": {
                "queryId": "department_summary",
                "options": _grouped_table_options(),
            }
        },
        "queries": queries,
    }


def upsert_examples(
    api_base: str,
    owner_id: str,
    system_token: str,
) -> list[dict[str, Any]]:
    base = api_base.rstrip("/")
    current = _request_json(
        f"{base}/api/reports?{urlencode({'owner_id': owner_id, 'limit': 200})}"
    )
    existing_by_title = {
        item["title"]: item
        for item in current.get("reports", [])
        if item.get("ownerId") == owner_id
    }
    saved: list[dict[str, Any]] = []
    for report in (
        build_simple_report(),
        build_complex_report(),
        build_complex_table_report(),
        build_multi_column_report(),
        build_independent_filters_report(),
        build_table_showcase_report(),
        build_image_layout_report(),
    ):
        payload = {"ownerId": owner_id, **report}
        existing = existing_by_title.get(report["title"])
        if existing:
            response = _request_json(
                f"{base}/api/reports/{existing['id']}",
                method="PUT",
                payload=payload,
            )
        else:
            response = _request_json(
                f"{base}/api/reports",
                method="POST",
                payload=payload,
            )
        saved_report = response["report"]
        _request_json(
            (
                f"{base}/api/internal/reports/"
                f"{saved_report['id']}/example"
            ),
            method="PUT",
            payload={"ownerId": owner_id, "isExample": True},
            system_token=system_token,
        )
        saved.append({**saved_report, "isExample": True})
    return saved


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    system_token: str | None = None,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if system_token:
        headers["X-GenBI-System-Token"] = system_token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{method} {url} failed with HTTP {exc.code}: {detail}"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update the ods.ods_dy_order Report examples."
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="GenBI backend API base URL.",
    )
    parser.add_argument(
        "--owner-id",
        default="local-user",
        help="Report center owner ID.",
    )
    parser.add_argument(
        "--system-token",
        default=os.getenv("GENBI_SYSTEM_API_TOKEN", ""),
        help="System API token used to publish public examples.",
    )
    args = parser.parse_args()
    reports = upsert_examples(
        args.api_base,
        args.owner_id,
        args.system_token,
    )
    for report in reports:
        print(f"{report['id']}\t{report['title']}")


if __name__ == "__main__":
    main()
