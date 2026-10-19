"""ASGI application and process liveness endpoint."""

from fastapi import FastAPI

app = FastAPI(title="OJ Platform", version="0.1.0")


@app.get("/healthz", tags=["operations"])
async def healthz() -> dict[str, str]:
    """Report process liveness without checking external dependencies."""
    return {"status": "ok"}
