from fastapi import FastAPI

from app.api.routes import router, tools_router

app = FastAPI(title="Sunday AI Agent", version="0.2.0")

# Include API routes
app.include_router(router)
app.include_router(tools_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Sunday AI Agent API", "version": "0.2.0"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}