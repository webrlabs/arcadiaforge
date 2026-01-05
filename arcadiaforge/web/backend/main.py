import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from arcadiaforge.web.backend.api import router as api_router
from arcadiaforge.web.backend.socket import router as socket_router

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="ArcadiaForge Web API")

# Allow CORS for local development (frontend usually on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(socket_router)

@app.get("/")
def health_check():
    return {"status": "ok", "service": "arcadiaforge-backend"}

if __name__ == "__main__":
    import uvicorn
    # Run on 0.0.0.0:8678
    uvicorn.run(app, host="0.0.0.0", port=8678)
