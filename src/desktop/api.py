"""Authenticated localhost API for the Electron desktop pet."""

from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.desktop.database import DesktopDatabase
from src.desktop.events import DesktopEventHub
from src.desktop.task_service import DesktopTaskService
from src.skill_library.registry import get_skill_registry


class CreateTaskRequest(BaseModel):
    conversation_id: str | None = None
    content: str = Field(min_length=1)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    title: str = "新会话"


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConfirmationRequest(BaseModel):
    comment: str = ""
    value: str = ""
    action_id: str = ""


def _masked(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}-****{value[-4:]}"


def create_app(
    *,
    token: str | None = None,
    database_path: str | Path | None = None,
) -> FastAPI:
    access_token = token or os.environ.get("DESKTOP_AGENT_TOKEN", "")
    if not access_token:
        raise RuntimeError("DESKTOP_AGENT_TOKEN is required")

    database = DesktopDatabase(database_path)
    events = DesktopEventHub()
    service = DesktopTaskService(database, events)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = database
        app.state.events = events
        app.state.task_service = service
        yield
        service.shutdown()

    app = FastAPI(title="Desktop Agent API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if authorization != f"Bearer {access_token}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    auth = Depends(authorize)

    @app.get("/api/health", dependencies=[auth])
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "desktop-agent"}

    @app.get("/api/runtime", dependencies=[auth])
    def runtime() -> dict[str, Any]:
        provider = os.getenv("LLM_PROVIDER", "openai")
        key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        model_name = (
            os.getenv("ANTHROPIC_MODEL", "")
            if provider == "anthropic"
            else os.getenv("OPENAI_MODEL", "")
        )
        return {
            "provider": provider,
            "model": model_name,
            "api_key_masked": _masked(os.getenv(key_name, "")),
            "browser_headless": os.getenv("BROWSER_HEADLESS", "false").lower() == "true",
        }

    @app.get("/api/conversations", dependencies=[auth])
    def conversations() -> list[dict[str, Any]]:
        return database.list_conversations()

    @app.post("/api/conversations", dependencies=[auth])
    def create_conversation(body: CreateConversationRequest) -> dict[str, Any]:
        import uuid

        return database.create_conversation(
            f"conversation_{uuid.uuid4().hex}", body.title.strip() or "新会话"
        )

    @app.patch("/api/conversations/{conversation_id}", dependencies=[auth])
    def rename_conversation(
        conversation_id: str, body: RenameConversationRequest
    ) -> dict[str, bool]:
        if not database.rename_conversation(conversation_id, body.title.strip()):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"ok": True}

    @app.delete("/api/conversations/{conversation_id}", dependencies=[auth])
    def delete_conversation(conversation_id: str) -> dict[str, bool]:
        if not database.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"ok": True}

    @app.delete("/api/conversations", dependencies=[auth])
    def clear_conversations() -> dict[str, bool]:
        database.clear_conversations()
        return {"ok": True}

    @app.get("/api/conversations/{conversation_id}/messages", dependencies=[auth])
    def messages(conversation_id: str) -> list[dict[str, Any]]:
        if database.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return database.list_messages(conversation_id)

    @app.post("/api/tasks", dependencies=[auth])
    def create_task(body: CreateTaskRequest) -> dict[str, Any]:
        try:
            return service.create_task(
                body.content,
                conversation_id=body.conversation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/tasks", dependencies=[auth])
    def tasks(conversation_id: str | None = None) -> list[dict[str, Any]]:
        return database.list_tasks(conversation_id)

    @app.post("/api/tasks/{task_id}/cancel", dependencies=[auth])
    def cancel_task(task_id: str) -> dict[str, bool]:
        if not service.cancel_task(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return {"ok": True}

    @app.post("/api/confirmations/{confirmation_id}/approve", dependencies=[auth])
    def approve_confirmation(
        confirmation_id: str, body: ConfirmationRequest
    ) -> dict[str, bool]:
        if not service.resolve_confirmation(
            confirmation_id,
            approved=True,
            comment=body.comment,
            value=body.value,
            action_id=body.action_id,
        ):
            raise HTTPException(status_code=409, detail="Confirmation already resolved")
        return {"ok": True}

    @app.post("/api/confirmations/{confirmation_id}/reject", dependencies=[auth])
    def reject_confirmation(
        confirmation_id: str, body: ConfirmationRequest
    ) -> dict[str, bool]:
        if not service.resolve_confirmation(
            confirmation_id,
            approved=False,
            comment=body.comment,
            value=body.value,
            action_id=body.action_id,
        ):
            raise HTTPException(status_code=409, detail="Confirmation already resolved")
        return {"ok": True}

    @app.get("/api/skills", dependencies=[auth])
    def skills() -> list[dict[str, Any]]:
        registry = get_skill_registry()
        return [
            {
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "description": item.description,
                "triggers": item.triggers,
                "version": item.version,
            }
            for item in registry.list_all()
        ]

    @app.get("/api/browser", dependencies=[auth])
    def browser_status() -> dict[str, Any]:
        from src.core.browser_manager import get_browser_manager

        browser = get_browser_manager()
        return {
            "running": browser.is_alive(),
            "engine": browser.engine,
            "url": browser.get_page().url if browser.is_alive() else "",
        }

    @app.post("/api/browser/close", dependencies=[auth])
    def close_browser() -> dict[str, bool]:
        return {"closed": service.close_browser()}

    @app.websocket("/api/events")
    async def event_socket(websocket: WebSocket) -> None:
        supplied = websocket.query_params.get("token")
        header = websocket.headers.get("authorization")
        if supplied != access_token and header != f"Bearer {access_token}":
            await websocket.close(code=4401)
            return
        await websocket.accept()
        queue = await events.connect()
        events.publish("backend_connected", payload={"connected": True})
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            events.disconnect(queue)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Desktop agent backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        raise SystemExit("Desktop backend must bind to 127.0.0.1")

    project_root = Path(__file__).resolve().parents[2]
    env_file = project_root / ".env"
    if env_file.exists():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)

    import uvicorn

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=args.port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
