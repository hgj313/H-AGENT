from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent.graphs.simple_graph.api.schemas import CreateSessionRequest, InterruptRequest
from agent.graphs.simple_graph.service import GraphService


app = FastAPI(title="Simple Graph Demo API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = GraphService(root_dir=str(Path.cwd() / ".graph_runtime"))
app.state.graph_service = service
frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/frontend", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def get_service() -> GraphService:
    return app.state.graph_service


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    index_path = frontend_dir / "index.html"
    return index_path.read_text(encoding="utf-8")


@app.post("/api/sessions")
def create_session(request: CreateSessionRequest) -> dict:
    payload = request.model_dump()
    user_id = payload.pop("user_id")
    return get_service().create_session(user_id=user_id, request_payload=payload)


@app.post("/api/sessions/{user_id}/{session_id}/start")
def start_session(user_id: str, session_id: str) -> dict:
    try:
        return get_service().start_session(user_id=user_id, session_id=session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/sessions/{user_id}/{session_id}/interrupt")
def interrupt_session(user_id: str, session_id: str, request: InterruptRequest) -> dict:
    try:
        return get_service().interrupt(user_id, session_id, request.action, request.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sessions/{user_id}/{session_id}")
def get_session_state(user_id: str, session_id: str) -> dict:
    try:
        return get_service().get_state(user_id=user_id, session_id=session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/sessions/{user_id}/{session_id}/snapshots")
def list_snapshots(user_id: str, session_id: str) -> dict:
    try:
        return {"snapshots": get_service().list_snapshots(user_id=user_id, session_id=session_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/sessions/{user_id}/{session_id}/rollback/{snapshot_id}")
def rollback_session(user_id: str, session_id: str, snapshot_id: str) -> dict:
    try:
        return get_service().rollback(user_id=user_id, session_id=session_id, snapshot_id=snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{user_id}/{session_id}/replay")
def replay_events(user_id: str, session_id: str) -> dict:
    return {"events": get_service().replay_events(user_id=user_id, session_id=session_id)}


@app.get("/api/sessions/{user_id}/{session_id}/events")
def stream_events(user_id: str, session_id: str, after_sequence: int = 0) -> StreamingResponse:
    def event_generator():
        for event in get_service().stream_events(
            user_id=user_id,
            session_id=session_id,
            after_sequence=after_sequence,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
