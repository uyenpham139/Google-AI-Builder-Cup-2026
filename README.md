# Echo

Echo is an advanced AI-powered platform designed to provide secure voice communications and prevent Contact Center Fraud (e.g., Authorized Push Payment Fraud) as a "Last Line of Defense". It leverages the Google Gemini Live API for real-time audio streaming and analysis.

## Repository Structure

This repository uses a monorepo architecture to manage both the frontend and backend services:

- **`frontend/`**: The frontend web application built with [Next.js (React)](https://nextjs.org/) and styled with TailwindCSS. It utilizes `shadcn/ui` and `zustand`. Managed via `pnpm` workspaces.
- **`backend/`**: The backend service built with [FastAPI (Python)](https://fastapi.tiangolo.com/), structured using Domain-Driven Design (DDD). It manages the **Multi-Agent Orchestrator** (Google ADK) and securely handles WebSocket audio streams with the Gemini Live API.

## Prerequisites

- [Node.js](https://nodejs.org/) & [pnpm](https://pnpm.io/) (for the Frontend)
- [Python 3](https://www.python.org/) (for the Backend)

## Getting Started

### 1. Frontend Setup
Navigate to the root directory and install Node.js dependencies using `pnpm`:
```bash
pnpm install
```
Start the frontend development server:
```bash
pnpm run dev:frontend
```
The frontend will be available at [http://localhost:3000](http://localhost:3000).

### 2. Backend Setup
Navigate to the `backend/` directory, set up a virtual environment, and install dependencies:
```bash
cd backend
python -m venv .venv

# Activate the virtual environment:
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
```
Start the backend development server:
```bash
fastapi dev app/main.py
```
The backend API will be available at [http://localhost:8000](http://localhost:8000).

### 3. Running with Docker Compose (Production Build)

You can run both the frontend (Next.js standalone) and backend (FastAPI Uvicorn) seamlessly using Docker Compose:

```bash
docker-compose up --build
```
- Frontend will be accessible at [http://localhost:3000](http://localhost:3000)
- Backend will be accessible at [http://localhost:8000](http://localhost:8000)

## Features In Development

- **Audio Streaming Spike**: A proof-of-concept for capturing microphone input via the Web Audio API and streaming chunks via WebSocket to the FastAPI backend, which will then interface with the Gemini Live API.

## License
See the [LICENSE](LICENSE) file for more details.
