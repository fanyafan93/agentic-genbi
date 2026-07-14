from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import JSONResponse

from app.schemas.analysis import AnalysisRequest, AnalysisTaskStatus, ApiError, ApiErrorResponse
from app.services.task_service import TaskCapacityExceeded, TaskNotFound, TaskService

router = APIRouter(prefix="/api/v1/analysis-tasks", tags=["analysis-tasks"])


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]


@router.post("", response_model=AnalysisTaskStatus, status_code=status.HTTP_202_ACCEPTED)
def create_analysis_task(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    task_service: TaskServiceDependency,
) -> AnalysisTaskStatus | JSONResponse:
    try:
        task = task_service.create_task(request)
    except TaskCapacityExceeded:
        return _error_response(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "TASK_CAPACITY_EXCEEDED",
            "分析任务容量已满，请稍后重试。",
        )
    background_tasks.add_task(task_service.run_analysis, task.task_id, request.question)
    return task


@router.get("/{task_id}", response_model=AnalysisTaskStatus)
def get_analysis_task(task_id: UUID, task_service: TaskServiceDependency) -> AnalysisTaskStatus | JSONResponse:
    try:
        return task_service.get_task(str(task_id))
    except TaskNotFound:
        return _error_response(
            status.HTTP_404_NOT_FOUND,
            "TASK_NOT_FOUND",
            "分析任务不存在或状态已因服务重启而丢失。",
        )


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiErrorResponse(error=ApiError(code=code, message=message))
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))
