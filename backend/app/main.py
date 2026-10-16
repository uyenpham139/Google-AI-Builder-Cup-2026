from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.websockets import audio
from app.api import alerts, erp, roleplay

app = FastAPI(title="Echo API - Multi Agent System")

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to Echo API"}

# Include routers
app.include_router(audio.router)
app.include_router(alerts.router)
app.include_router(erp.router)
app.include_router(roleplay.router)


