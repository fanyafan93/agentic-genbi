import argparse
import json
import math
import re
from pathlib import Path


SEMANTIC_ALIASES = {
    "brand": {
        "triggers": ["品牌", "飞科", "博锐", "素士", "徕芬"],
        "terms": ["品牌", "vbrand", "brand"],
    },
    "sales": {
        "triggers": ["销售", "销售额", "销售情况", "动销"],
        "terms": ["销售", "销售额", "成交金额", "GMV", "gmv", "ngmv", "sale"],
    },
    "refund": {
        "triggers": ["退款", "退款率", "退货"],
        "terms": ["退款", "退款率", "退货", "refund", "return"],
    },
    "region": {
        "triggers": ["华东", "华东区", "区域", "大区", "地区", "省份", "城市"],
        "terms": ["区域", "大区", "地区", "省份", "城市", "region", "area"],
    },
    "channel": {
        "triggers": ["渠道", "线上", "线下", "平台"],
        "terms": ["渠道", "渠道类型", "平台", "线上", "线下", "channel", "platform"],
    },
    "income": {
        "triggers": ["收入", "收入净额"],
        "terms": ["收入", "收入净额", "确认收入", "income"],
    },
    "profit": {
        "triggers": ["利润", "经营利润", "毛利"],
        "terms": ["利润", "经营利润", "经营利润额", "毛利", "profit", "nprofit"],
    },
    "time": {
        "triggers": ["月", "本月", "这个月", "7月", "日期", "时间"],
        "terms": ["日期", "时间", "月份", "月", "MTD", "vdate", "vmonth"],
    },
}

NON_ANALYSIS_REPORT_TERMS = ["填报", "导入", "校验", "预测", "自查", "异常"]
GENERAL_SCOPE_TERMS = ["多平台", "全渠道", "总览", "管报"]
PLATFORM_TERMS = ["京东", "抖音", "天猫", "拼多多", "美团", "快手", "视频号", "Tiktok", "1688", "得物", "唯品会"]
SKIP_KEYS = {"cell", "row", "column", "formula", "dependencies", "condition"}


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def walk_strings(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SKIP_KEYS:
                continue
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)
    elif isinstance(value, str):
        yield value


def infer_request(question):
    dimensions = []
    metrics = []
    filters = []
    concepts = []
    for concept, config in SEMANTIC_ALIASES.items():
        if any(trigger.lower() in question.lower() for trigger in config["triggers"]):
            concepts.append(concept)
    for concept in concepts:
        if concept in {"brand", "region", "channel", "time"}:
            dimensions.append(concept)
        if concept in {"sales", "refund", "income", "profit"}:
            metrics.append(concept)
    for trigger in SEMANTIC_ALIASES["region"]["triggers"]:
        if trigger in question and trigger not in {"区域", "大区", "地区", "省份", "城市"}:
            filters.append({"semantic_type": "region", "value": trigger})
    for trigger in SEMANTIC_ALIASES["brand"]["triggers"]:
        if trigger in question and trigger != "品牌":
            filters.append({"semantic_type": "brand", "value": trigger})
    return {
        "question": question,
        "concepts": concepts,
        "metrics": metrics,
        "dimensions": dimensions,
        "filters": filters,
    }


def report_text(payload):
    report = payload.get("report", {}) if isinstance(payload.get("report"), dict) else {}
    name = clean_text(report.get("name"))
    body = clean_text(" ".join(walk_strings(payload.get("report_structure", {}))))
    interaction = clean_text(" ".join(walk_strings(payload.get("parameters_and_interactions", {}))))
    dataset = []
    sql = []
    for item in payload.get("datasets", []):
        if not isinstance(item, dict):
            continue
        dataset.append(clean_text(item.get("name")))
        dataset.append(clean_text(item.get("connection_name")))
        sql.append(clean_text(item.get("raw_sql")))
    return {
        "name": name,
        "body": body,
        "interaction": interaction,
        "dataset": " ".join(dataset),
        "sql": " ".join(sql),
        "body_or_interaction": f"{body} {interaction}",
    }


def candidate_pool_match(texts, concepts):
    if not concepts:
        return True
    required_terms = []
    for concept in concepts:
        required_terms.extend(SEMANTIC_ALIASES[concept]["terms"])
    body_or_interaction = texts["body_or_interaction"].lower()
    return any(term.lower() in body_or_interaction for term in required_terms)


def score_report(question_intent, payload, path, profiles_dir):
    texts = report_text(payload)
    if not candidate_pool_match(texts, question_intent["concepts"]):
        return None

    related_score = 0
    hits = []
    for concept in question_intent["concepts"]:
        concept_hit = False
        for term in SEMANTIC_ALIASES[concept]["terms"]:
            term_lower = term.lower()
            if term_lower in texts["name"].lower():
                related_score += 10
                hits.append(f"{term}@name")
                concept_hit = True
                break
            if term_lower in texts["body"].lower():
                related_score += 6
                hits.append(f"{term}@body")
                concept_hit = True
                break
            if term_lower in texts["interaction"].lower():
                related_score += 5
                hits.append(f"{term}@interaction")
                concept_hit = True
                break
            if term_lower in texts["dataset"].lower():
                related_score += 4
                hits.append(f"{term}@dataset")
                concept_hit = True
                break
            if term_lower in texts["sql"].lower():
                related_score += 2
                hits.append(f"{term}@sql")
                concept_hit = True
                break
        if not concept_hit:
            related_score -= 8
            hits.append(f"{concept}@missing")

    if "brand" in question_intent["concepts"] and "sales" in question_intent["concepts"]:
        if any(term in texts["body_or_interaction"] for term in SEMANTIC_ALIASES["brand"]["terms"]) and any(
            term in texts["body_or_interaction"] for term in SEMANTIC_ALIASES["sales"]["terms"]
        ):
            related_score += 10
            hits.append("brand+sales@body_or_interaction")

    if "refund" in question_intent["concepts"] and "region" in question_intent["concepts"]:
        if any(term in texts["body_or_interaction"] for term in SEMANTIC_ALIASES["refund"]["terms"]) and any(
            term in texts["body_or_interaction"] for term in SEMANTIC_ALIASES["region"]["terms"]
        ):
            related_score += 12
            hits.append("refund+region@body_or_interaction")

    if "income" in question_intent["concepts"] and "profit" in question_intent["concepts"]:
        if any(term in texts["body_or_interaction"] for term in SEMANTIC_ALIASES["income"]["terms"]) and any(
            term in texts["body_or_interaction"] for term in SEMANTIC_ALIASES["profit"]["terms"]
        ):
            related_score += 12
            hits.append("income+profit@body_or_interaction")

    name = texts["name"]
    if any(term in name for term in GENERAL_SCOPE_TERMS):
        related_score += 4
        hits.append("general_scope@name")
    if not any(term in question for term in PLATFORM_TERMS) and any(term in name for term in PLATFORM_TERMS):
        related_score -= 4
        hits.append("platform_limited_without_platform_request@name")
    if any(term in name for term in NON_ANALYSIS_REPORT_TERMS):
        related_score -= 8
        hits.append("non_analysis_report_penalty@name")

    usage = payload.get("report_usage", {}) if isinstance(payload.get("report_usage"), dict) else {}
    usage_count = usage.get("total_usage_count") or 0
    usage_score = min(20, round(math.log1p(usage_count) * 4, 2))
    total_score = related_score + usage_score
    if total_score < 8:
        return None
    return {
        "report_name": name or path.stem,
        "profile_json_path": str(path.relative_to(profiles_dir)).replace("\\", "/"),
        "source_cpt_path": clean_text(payload.get("report", {}).get("source_cpt_path")),
        "total_score": round(total_score, 2),
        "related_score": related_score,
        "usage_score": usage_score,
        "usage_count": usage_count,
        "hits": hits[:12],
    }


def search_reports(profiles_dir, question, limit):
    profiles_dir = Path(profiles_dir)
    intent = infer_request(question)
    results = []
    for path in sorted(profiles_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = score_report(intent, payload, path, profiles_dir)
        if result:
            results.append(result)
    results.sort(key=lambda item: (-item["total_score"], -item["usage_count"], item["profile_json_path"]))
    return {"intent": intent, "candidate_count": len(results), "results": results[:limit]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--profiles-dir", default="资源库/finereport/报表画像")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(search_reports(args.profiles_dir, args.question, args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
