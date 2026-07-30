from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_ANALYSIS_ASSET_STORE_PATH = Path(".resource-index/analysis-assets.jsonl")


@dataclass(frozen=True)
class AnalysisAssetReopenContext:
    sourceTaskId: str
    sourceConversationId: str
    sourceRunId: str
    continuationPrompt: str
    targetFileId: str | None = None


@dataclass(frozen=True)
class AnalysisAssetRecord:
    assetId: str
    artifactVersionId: str
    sourceTaskId: str
    sourceTaskTitle: str
    sourceConversationId: str
    sourceRunId: str
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
    metadata: dict[str, Any] = field(default_factory=dict)


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
        source_run_id: str,
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
            "source_run_id": source_run_id,
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

        now = datetime.now(UTC).isoformat()
        existing = self.get_asset(asset_id)
        record = AnalysisAssetRecord(
            assetId=asset_id.strip(),
            artifactVersionId=artifact_version_id.strip(),
            sourceTaskId=source_task_id.strip(),
            sourceTaskTitle=source_task_title.strip(),
            sourceConversationId=source_conversation_id.strip(),
            sourceRunId=source_run_id.strip(),
            assetType=asset_type.strip(),
            title=title.strip(),
            label=label.strip(),
            description=description.strip(),
            visibility=visibility.strip(),
            status=status.strip(),
            latestVersion=latest_version.strip(),
            fileId=file_id.strip() if file_id else None,
            reopenContext=reopen_context,
            createdAt=existing.createdAt if existing else now,
            updatedAt=now,
            metadata=metadata or {},
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
            payload["reopenContext"] = AnalysisAssetReopenContext(**payload.get("reopenContext", {}))
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


def _validate_reopen_context(context: AnalysisAssetReopenContext) -> None:
    _require_text("reopen_context.sourceTaskId", context.sourceTaskId)
    _require_text("reopen_context.sourceConversationId", context.sourceConversationId)
    _require_text("reopen_context.sourceRunId", context.sourceRunId)
    _require_text("reopen_context.continuationPrompt", context.continuationPrompt)
