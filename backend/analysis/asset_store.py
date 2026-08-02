from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_ANALYSIS_ASSET_STORE_PATH = Path(".resource-index/analysis-assets.jsonl")


@dataclass(frozen=True)
class AnalysisAssetReopenContext:
    sourceTaskId: str
    sourceConversationId: str
    continuationPrompt: str
    targetFileId: str | None = None
    sourceCodexThreadId: str | None = None
    sourceCodexTurnId: str | None = None
    sourceCodexItemId: str | None = None


@dataclass(frozen=True)
class AnalysisAssetRecord:
    assetId: str
    artifactVersionId: str
    sourceTaskId: str
    sourceTaskTitle: str
    sourceConversationId: str
    assetType: str
    title: str
    label: str
    description: str
    visibility: str
    status: str
    latestVersion: str
    reopenContext: AnalysisAssetReopenContext
    createdAt: str
    updatedAt: str
    fileId: str | None = None
    sourceCodexThreadId: str | None = None
    sourceCodexTurnId: str | None = None
    sourceCodexItemId: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactLineageRecord:
    artifactId: str
    artifactVersionId: str
    assetId: str
    assetType: str
    title: str
    sourceTaskId: str
    sourceConversationId: str
    codexThreadId: str | None
    codexTurnId: str | None
    codexItemId: str | None
    createdAt: str
    updatedAt: str


class AnalysisAssetStore:
    def __init__(self, path: Path = DEFAULT_ANALYSIS_ASSET_STORE_PATH) -> None:
        self.path = path

    def save_asset(
        self,
        *,
        asset_id: str,
        artifact_version_id: str,
        source_task_id: str,
        source_task_title: str,
        source_conversation_id: str,
        source_codex_thread_id: str | None = None,
        source_codex_turn_id: str | None = None,
        source_codex_item_id: str | None = None,
        asset_type: str,
        title: str,
        label: str,
        description: str,
        visibility: str,
        status: str,
        latest_version: str,
        reopen_context: AnalysisAssetReopenContext,
        file_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisAssetRecord:
        for field_name, value in {
            "asset_id": asset_id,
            "artifact_version_id": artifact_version_id,
            "source_task_id": source_task_id,
            "source_task_title": source_task_title,
            "source_conversation_id": source_conversation_id,
            "asset_type": asset_type,
            "title": title,
            "label": label,
            "description": description,
            "visibility": visibility,
            "status": status,
            "latest_version": latest_version,
        }.items():
            _require_text(field_name, value)
        _validate_reopen_context(reopen_context)
        normalized_reopen_context = AnalysisAssetReopenContext(
            sourceTaskId=reopen_context.sourceTaskId,
            sourceConversationId=reopen_context.sourceConversationId,
            continuationPrompt=reopen_context.continuationPrompt,
            targetFileId=reopen_context.targetFileId,
            sourceCodexThreadId=reopen_context.sourceCodexThreadId,
            sourceCodexTurnId=reopen_context.sourceCodexTurnId,
            sourceCodexItemId=reopen_context.sourceCodexItemId,
        )

        now = datetime.now(UTC).isoformat()
        existing = self.get_asset(asset_id)
        codex_lineage = _codex_lineage(source_codex_thread_id, source_codex_turn_id, source_codex_item_id)
        record_metadata = dict(metadata or {})
        if codex_lineage:
            record_metadata["codex_lineage"] = codex_lineage
        record = AnalysisAssetRecord(
            assetId=asset_id.strip(),
            artifactVersionId=artifact_version_id.strip(),
            sourceTaskId=source_task_id.strip(),
            sourceTaskTitle=source_task_title.strip(),
            sourceConversationId=source_conversation_id.strip(),
            sourceCodexThreadId=_optional_text(source_codex_thread_id),
            sourceCodexTurnId=_optional_text(source_codex_turn_id),
            sourceCodexItemId=_optional_text(source_codex_item_id),
            assetType=asset_type.strip(),
            title=title.strip(),
            label=label.strip(),
            description=description.strip(),
            visibility=visibility.strip(),
            status=status.strip(),
            latestVersion=latest_version.strip(),
            fileId=file_id.strip() if file_id else None,
            reopenContext=normalized_reopen_context,
            createdAt=existing.createdAt if existing else now,
            updatedAt=now,
            metadata=record_metadata,
        )
        records = [item for item in self._read_all() if item.assetId != record.assetId]
        records.append(record)
        self._write_all(records)
        return record

    def list_assets(
        self,
        *,
        limit: int = 50,
        source_task_id: str | None = None,
        q: str = "",
    ) -> list[AnalysisAssetRecord]:
        query = q.strip().lower()
        records = self._read_all()
        matched = []
        for record in records:
            if source_task_id and record.sourceTaskId != source_task_id:
                continue
            haystack = " ".join(
                [
                    record.assetId,
                    record.sourceTaskTitle,
                    record.assetType,
                    record.title,
                    record.label,
                    record.description,
                    json.dumps(record.metadata, ensure_ascii=False, default=str),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            matched.append(record)
        matched.sort(key=lambda item: item.updatedAt, reverse=True)
        return matched[:limit]

    def get_asset(self, asset_id: str) -> AnalysisAssetRecord | None:
        for record in self._read_all():
            if record.assetId == asset_id:
                return record
        return None

    def reopen_asset(self, asset_id: str) -> dict[str, Any] | None:
        record = self.get_asset(asset_id)
        if not record:
            return None
        return {
            "context": asdict(record.reopenContext),
            "assetId": record.assetId,
            "artifactVersionId": record.artifactVersionId,
            "openedAt": datetime.now(UTC).isoformat(),
        }

    def list_artifact_lineage(
        self,
        *,
        artifact_id: str | None = None,
        codex_thread_id: str | None = None,
        codex_turn_id: str | None = None,
        codex_item_id: str | None = None,
        limit: int = 50,
    ) -> list[ArtifactLineageRecord]:
        lineage = [_artifact_lineage_from_asset(record) for record in self._read_all()]
        lineage = [
            record
            for record in lineage
            if (
                (not artifact_id or record.artifactId == artifact_id)
                and (not codex_thread_id or record.codexThreadId == codex_thread_id)
                and (not codex_turn_id or record.codexTurnId == codex_turn_id)
                and (not codex_item_id or record.codexItemId == codex_item_id)
            )
        ]
        lineage.sort(key=lambda item: item.updatedAt, reverse=True)
        return lineage[:limit]

    def delete_asset(self, asset_id: str) -> bool:
        records = self._read_all()
        remaining = [record for record in records if record.assetId != asset_id]
        if len(remaining) == len(records):
            return False
        self._write_all(remaining)
        return True

    def clear_assets(self) -> int:
        count = len(self._read_all())
        if self.path.exists():
            self.path.unlink()
        return count

    def _read_all(self) -> list[AnalysisAssetRecord]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            payload = _filter_dataclass_payload(payload, AnalysisAssetRecord)
            reopen_context_payload = payload.get("reopenContext", {})
            reopen_context_payload = _filter_dataclass_payload(reopen_context_payload, AnalysisAssetReopenContext)
            payload["reopenContext"] = AnalysisAssetReopenContext(**reopen_context_payload)
            records.append(AnalysisAssetRecord(**payload))
        return records

    def _write_all(self, records: list[AnalysisAssetRecord]) -> None:
        if not records:
            if self.path.exists():
                self.path.unlink()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        records.sort(key=lambda item: item.updatedAt)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in records:
                file.write(json.dumps(asdict(record), ensure_ascii=False, default=str))
                file.write("\n")


def _require_text(field: str, value: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field} is required.")


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _codex_lineage(
    codex_thread_id: str | None,
    codex_turn_id: str | None,
    codex_item_id: str | None,
) -> dict[str, str]:
    lineage = {
        "codexThreadId": _optional_text(codex_thread_id),
        "codexTurnId": _optional_text(codex_turn_id),
        "codexItemId": _optional_text(codex_item_id),
    }
    return {key: value for key, value in lineage.items() if value}


def _artifact_lineage_from_asset(record: AnalysisAssetRecord) -> ArtifactLineageRecord:
    return ArtifactLineageRecord(
        artifactId=record.assetId,
        artifactVersionId=record.artifactVersionId,
        assetId=record.assetId,
        assetType=record.assetType,
        title=record.title,
        sourceTaskId=record.sourceTaskId,
        sourceConversationId=record.sourceConversationId,
        codexThreadId=record.sourceCodexThreadId,
        codexTurnId=record.sourceCodexTurnId,
        codexItemId=record.sourceCodexItemId,
        createdAt=record.createdAt,
        updatedAt=record.updatedAt,
    )


def _validate_reopen_context(context: AnalysisAssetReopenContext) -> None:
    _require_text("reopen_context.sourceTaskId", context.sourceTaskId)
    _require_text("reopen_context.sourceConversationId", context.sourceConversationId)
    _require_text("reopen_context.continuationPrompt", context.continuationPrompt)


def _filter_dataclass_payload(payload: dict[str, Any], target: type[Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(target)}
    return {key: value for key, value in payload.items() if key in allowed}
