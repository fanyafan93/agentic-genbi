from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.analysis_tasks import router as analysis_tasks_router
from app.config import Settings, get_settings
from app.schemas.analysis import ApiError, ApiErrorResponse
from app.services.task_service import TaskService


def create_app(
    settings: Settings | None = None, task_service: TaskService | None = None
) -> FastAPI:
    """Create the HTTP application with already-validated runtime settings."""

    app = FastAPI(title="Agentic GenBI MVP")
    app.state.settings = settings or get_settings()
    app.state.task_service = task_service or TaskService()

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
        response = ApiErrorResponse(
            error=ApiError(code="VALIDATION_ERROR", message="请求参数无效。")
        )
        return JSONResponse(status_code=422, content=response.model_dump(mode="json"))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(analysis_tasks_router)

    return app


app = create_app()
