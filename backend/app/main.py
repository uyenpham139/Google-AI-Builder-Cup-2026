from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.rest import risk
from app.api.websockets import audio, events

app = FastAPI(title="Echo API - Multi Agent System")

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to Echo API"}

# Include routers
app.include_router(audio.router)
app.include_router(events.router)
app.include_router(risk.router)
