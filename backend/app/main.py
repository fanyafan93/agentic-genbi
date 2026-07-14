from fastapi import FastAPI

from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP application with already-validated runtime settings."""

    app = FastAPI(title="Agentic GenBI MVP")
    app.state.settings = settings or get_settings()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
