import pytest

from app.agents.runner import AgentProviderNotConfigured
from app.schemas.analysis import AnalysisRequest, TaskState
from app.services.task_service import TaskCapacityExceeded, TaskNotFound, TaskService
from tests.fixtures.fixed_report import make_fixed_report


def test_task_lifecycle_exposes_terminal_fields_only_after_success() -> None:
    service = TaskService()

    queued = service.create_task(AnalysisRequest(question="  查看固定报告  "))
    running = service.start_task(queued.task_id)
    succeeded = service.succeed_task(queued.task_id, make_fixed_report())

    assert queued.status is TaskState.QUEUED
    assert queued.report is None
    assert queued.completed_at is None
    assert running.status is TaskState.RUNNING
    assert running.report is None
    assert running.completed_at is None
    assert succeeded.status is TaskState.SUCCEEDED
    assert succeeded.report == make_fixed_report()
    assert succeeded.completed_at is not None


def test_registry_allows_only_one_non_terminal_task_for_single_worker_mvp() -> None:
    service = TaskService()
    service.create_task(AnalysisRequest(question="第一个任务"))

    with pytest.raises(TaskCapacityExceeded):
        service.create_task(AnalysisRequest(question="第二个任务"))


def test_registry_returns_not_found_after_state_is_lost_or_id_is_unknown() -> None:
    service = TaskService()

    with pytest.raises(TaskNotFound):
        service.get_task("00000000-0000-0000-0000-000000000000")


def test_task_service_maps_agent_configuration_error_to_failed_task() -> None:
    def unavailable_runner(_: str):
        raise AgentProviderNotConfigured

    service = TaskService(analysis_runner=unavailable_runner)
    task = service.create_task(AnalysisRequest(question="How did sales change?"))

    service.run_analysis(task.task_id, "How did sales change?")

    failed_task = service.get_task(task.task_id)
    assert failed_task.status == "failed"
    assert failed_task.report is None
    assert failed_task.error is not None
    assert failed_task.error.code == "PROVIDER_NOT_CONFIGURED"
    assert failed_task.error.message == "Analysis provider is not configured."
