from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Protocol

from backend.analysis.report_query_service import build_report_query_prompt_context, is_registered_report_query_ref
from backend.exploration.agent_runner import ExplorationAgentRunnerEvent


INTERACTIVE_REPORT_DRAFT_TAG = "interactive_report_draft"
_INTERACTIVE_REPORT_DRAFT_RE = re.compile(
    rf"\s*<{INTERACTIVE_REPORT_DRAFT_TAG}>\s*(?P<payload>\{{.*?\}})\s*</{INTERACTIVE_REPORT_DRAFT_TAG}>\s*",
    re.DOTALL,
)


@dataclass(frozen=True)
class AnalysisAgentRunResult:
    final_output: str
    raw_result_type: str
    events: list[ExplorationAgentRunnerEvent] = field(default_factory=list)


class AnalysisAgentRunner(Protocol):
    def run(self, prompt: str) -> AnalysisAgentRunResult: ...

    def stream(self, prompt: str) -> Iterable[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]: ...

    def async_stream(self, prompt: str) -> AsyncIterator[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]: ...


def build_analysis_runner_prompt(
    *,
    question: str,
    problem_label: str,
    semantic_model_labels: list[str],
    current_report_context: dict[str, Any] | None = None,
) -> str:
    lines = [
            f"用户问题：{question}",
            f"初步问题类型：{problem_label}",
            "可参考的语义模型：",
            *[f"- {label}" for label in semantic_model_labels],
            "请输出适合分析任务前端展示的中文回复，并明确下一步需要生成或更新的分析资产。",
            build_report_query_prompt_context(),
            "当且仅当你能在不编造业务数据的前提下生成或修改交互式分析结果时，可在回复末尾附上一个 JSON：",
            "<interactive_report_draft>{...}</interactive_report_draft>。JSON 必须包含 title、subtitle、document、filters、queries、chartSpecs、gridSpecs。",
            "document 必须是 Puck 文档对象（含 root、content、zones）。content 只使用 SectionBlock、MarkdownBlock、KpiBlock、ChartBlock、GridBlock、EvidenceBlock。",
            "若使用已登记查询，ChartBlock/GridBlock 的 queryRef、queries 键与 chartSpecs/gridSpecs 的 datasetId 必须一致；没有真实工具结果时，只能写待验证假设，不得写具体金额、占比或增长结论。",
            "不要在普通回复中解释或重复该 JSON。",
    ]
    if current_report_context:
        lines.extend(
            [
                "用户正在继续修改以下交互式分析结果。本轮交付必须是在回复末尾输出完整的新 <interactive_report_draft>，而不是描述一个未落地的修改建议。请将其视为当前基线：保留不受本轮请求影响的结构和已登记 queryRef。",
                "草稿标签内必须是严格 RFC 8259 JSON：字符串中的换行、制表符必须写成 \\n、\\t 等转义，不要使用 Markdown 代码块，不要在 JSON 之外附加说明。",
                "顶层结构必须严格如下，filters、queries、chartSpecs、gridSpecs 绝不能放进 document：{\"title\":\"...\",\"subtitle\":\"...\",\"document\":{\"root\":{},\"content\":[],\"zones\":{}},\"filters\":[],\"queries\":{},\"chartSpecs\":{},\"gridSpecs\":{}}。",
                json.dumps(current_report_context, ensure_ascii=False, separators=(",", ":")),
            ]
        )
    return "\n".join(lines)


def sanitize_interactive_report_context(value: Any, *, max_bytes: int = 60_000) -> dict[str, Any] | None:
    """Accept only the report fields the model needs to revise, with a bounded prompt size."""

    if not isinstance(value, dict):
        return None
    payload = {
        key: value.get(key)
        for key in ("id", "title", "subtitle", "document", "filters", "queries", "chartSpecs", "gridSpecs")
    }
    if not isinstance(payload.get("id"), str) or not payload["id"].strip():
        return None
    report_payload = {key: value for key, value in payload.items() if key != "id"}
    if not _is_interactive_report_draft(report_payload):
        return None
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload if len(encoded) <= max_bytes else None


def extract_interactive_report_draft(final_output: str) -> tuple[str, dict[str, Any] | None]:
    """Extract one explicit report draft without treating arbitrary prose as report data."""

    match = _INTERACTIVE_REPORT_DRAFT_RE.search(final_output)
    if not match:
        return final_output.strip(), None
    try:
        payload = _normalize_interactive_report_draft(_decode_interactive_report_draft(match.group("payload")))
    except json.JSONDecodeError:
        return final_output.strip(), None
    payload = _discard_unregistered_report_query_refs(payload)
    if not _is_interactive_report_draft(payload):
        return final_output.strip(), None
    message = (final_output[:match.start()] + final_output[match.end():]).strip()
    return message, payload


def _discard_unregistered_report_query_refs(payload: Any) -> Any:
    """Keep the safe portion of a mixed draft instead of dropping all registered report content."""

    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), dict):
        return payload
    queries = payload["queries"]
    unknown_refs = [str(query_ref) for query_ref in queries if not is_registered_report_query_ref(str(query_ref))]
    if not unknown_refs:
        return payload
    registered_queries = {query_ref: value for query_ref, value in queries.items() if is_registered_report_query_ref(str(query_ref))}
    if not registered_queries:
        return payload

    sanitized = dict(payload)
    sanitized["queries"] = registered_queries
    removed_dataset_ids = {
        str(value.get("datasetId"))
        for query_ref, value in queries.items()
        if str(query_ref) in unknown_refs and isinstance(value, dict) and isinstance(value.get("datasetId"), str)
    }
    for spec_key in ("chartSpecs", "gridSpecs"):
        specs = sanitized.get(spec_key)
        if isinstance(specs, dict):
            sanitized[spec_key] = {
                spec_id: spec
                for spec_id, spec in specs.items()
                if not (isinstance(spec, dict) and str(spec.get("datasetId")) in removed_dataset_ids)
            }
    document = sanitized.get("document")
    if isinstance(document, dict) and isinstance(document.get("content"), list):
        sanitized_document = dict(document)
        sanitized_document["content"] = [
            block
            for block in document["content"]
            if not (
                isinstance(block, dict)
                and isinstance(block.get("props"), dict)
                and str(block["props"].get("queryRef") or "") in unknown_refs
            )
        ]
        sanitized["document"] = sanitized_document
    return sanitized


def _normalize_interactive_report_draft(payload: Any) -> Any:
    """Lift one known model nesting error into the report contract before validation."""

    if not isinstance(payload, dict):
        return payload
    document = payload.get("document")
    required_fields = ("filters", "queries", "chartSpecs", "gridSpecs")
    nested_document = isinstance(document, dict) and isinstance(document.get("root"), dict)
    nested_root = document.get("root") if nested_document else None
    if (
        nested_document
        and isinstance(nested_root.get("content"), list)
        and isinstance(nested_root.get("zones"), dict)
        and all(name not in payload and name in document for name in required_fields)
    ):
        normalized = dict(payload)
        normalized["document"] = nested_root
        for name in required_fields:
            normalized[name] = document[name]
        payload = normalized
    document = payload.get("document") if isinstance(payload, dict) else None
    if (
        isinstance(document, dict)
        and "root" not in document
        and isinstance(document.get("props"), dict)
        and isinstance(document.get("content"), list)
        and isinstance(document.get("zones"), dict)
    ):
        normalized = dict(payload)
        normalized["document"] = {
            "root": {"props": document["props"]},
            "content": document["content"],
            "zones": document["zones"],
        }
        return normalized
    return payload


def _decode_interactive_report_draft(raw_json: str) -> Any:
    """Accept one JSON object, tolerating only small trailing-brace mistakes from a model."""

    decoder = json.JSONDecoder()
    normalized = _complete_trailing_object_braces(_escape_unescaped_string_controls(raw_json))
    payload, end = decoder.raw_decode(normalized)
    remainder = normalized[end:].strip()
    if remainder and set(remainder) != {"}"}:
        raise json.JSONDecodeError("unexpected content after interactive report draft", normalized, end)
    return payload


def _complete_trailing_object_braces(raw_json: str) -> str:
    """Complete only a bounded number of missing object closers after a complete JSON string/array body."""

    in_string = False
    backslash_run = 0
    object_balance = 0
    array_balance = 0
    for character in raw_json:
        if character == '"' and backslash_run % 2 == 0:
            in_string = not in_string
        elif not in_string:
            if character == "{":
                object_balance += 1
            elif character == "}":
                object_balance -= 1
            elif character == "[":
                array_balance += 1
            elif character == "]":
                array_balance -= 1
        backslash_run = backslash_run + 1 if character == "\\" else 0
    if not in_string and array_balance == 0 and 0 < object_balance <= 3:
        return raw_json + ("}" * object_balance)
    return raw_json


def _escape_unescaped_string_controls(raw_json: str) -> str:
    """Repair model JSON only where raw control characters make a string invalid."""

    escaped: list[str] = []
    in_string = False
    backslash_run = 0
    for character in raw_json:
        if character == '"' and backslash_run % 2 == 0:
            in_string = not in_string
        if in_string and ord(character) < 0x20:
            escaped.append(json.dumps(character)[1:-1])
        else:
            escaped.append(character)
        backslash_run = backslash_run + 1 if character == "\\" else 0
    return "".join(escaped)


def _is_interactive_report_draft(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if not all(isinstance(payload.get(key), str) and payload[key].strip() for key in ("title", "subtitle")):
        return False
    document = payload.get("document")
    if not isinstance(document, dict) or not isinstance(document.get("root"), dict):
        return False
    if not isinstance(document.get("content"), list) or not isinstance(document.get("zones"), dict):
        return False
    if not all(isinstance(payload.get(key), expected) for key, expected in (
        ("filters", list),
        ("queries", dict),
        ("chartSpecs", dict),
        ("gridSpecs", dict),
    )):
        return False
    return all(is_registered_report_query_ref(str(query_ref)) for query_ref in payload["queries"])
