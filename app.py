from __future__ import annotations

import hashlib
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
from rh_client import RunningHubClient, RunningHubError, fetch_webapp_schema, interpret_outputs
from sample_data import SAMPLE_SCHEMA, SAMPLE_WEBAPP_ID
from schema import SchemaError, build_submit_nodes, extract_webapp_id

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
load_dotenv(ROOT / ".env")

_stop_event = threading.Event()
_poller: threading.Thread | None = None


class SettingsIn(BaseModel):
    api_key: str = ""


class ImportIn(BaseModel):
    webappId: str | None = None
    url: str | None = None
    demo: bool = False


class ToolUpdateIn(BaseModel):
    display_name: str | None = None
    category: str | None = None
    description: str | None = None
    enabled: bool | None = None
    fields: list[dict] = Field(default_factory=list)


class TaskCreateIn(BaseModel):
    tool_id: int
    values: dict = Field(default_factory=dict)
    instance_type: str = "default"


def require_api_key() -> str:
    api_key = db.get_setting("api_key") or os.getenv("RUNNINGHUB_API_KEY", "")
    if not api_key.strip():
        raise HTTPException(status_code=400, detail="请先在设置页填写 RunningHub API Key")
    return api_key.strip()


def client_from_settings() -> RunningHubClient:
    return RunningHubClient(require_api_key())


def import_schema(webapp_id: str, demo: bool = False) -> dict:
    warning = ""
    if demo:
        schema = {
            "webappId": SAMPLE_WEBAPP_ID,
            "name": SAMPLE_SCHEMA["webappName"],
            "cover_url": SAMPLE_SCHEMA.get("coverUrl") or "",
            "nodeInfoList": SAMPLE_SCHEMA["nodeInfoList"],
            "raw": SAMPLE_SCHEMA,
            "empty_nodes": False,
            "source": "demo",
        }
        warning = "当前使用官方文档示例参数。直接贴应用 ID 可从公开页拉取真实参数，不需要 API Key。"
    else:
        api_key = (db.get_setting("api_key") or os.getenv("RUNNINGHUB_API_KEY", "")).strip()
        try:
            schema = fetch_webapp_schema(webapp_id, api_key)
        except RunningHubError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if schema.get("empty_nodes"):
            warning = "该应用没有返回可修改节点。请先在 RunningHub 网页端成功运行一次，再点刷新。"
        elif schema.get("source") == "public" and not api_key:
            warning = "已从公开页拉取参数，提交运行仍需要在设置里填 API Key。"

    tool = db.upsert_tool_from_schema(
        webapp_id=schema["webappId"],
        name=schema["name"],
        cover_url=schema.get("cover_url") or "",
        raw_schema=schema.get("raw") or schema,
        node_info_list=schema.get("nodeInfoList") or [],
        warning=warning,
    )
    return tool


def poll_once() -> None:
    pending = db.list_pending_tasks()
    if not pending:
        return
    api_key = db.get_setting("api_key") or os.getenv("RUNNINGHUB_API_KEY", "")
    if not api_key.strip():
        return
    try:
        client = RunningHubClient(api_key)
    except RunningHubError:
        return
    try:
        for task in pending:
            try:
                payload = client.query_outputs(task["rh_task_id"])
                result = interpret_outputs(payload)
                db.update_task(
                    task["id"],
                    status=result["status"],
                    status_code=result["status_code"],
                    outputs=result["outputs"],
                    error_message=result["error"],
                )
            except Exception as exc:
                db.update_task(task["id"], error_message=str(exc))
    finally:
        client.close()


def poll_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            poll_once()
        except Exception:
            pass
        stop_event.wait(2.0)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    env_key = os.getenv("RUNNINGHUB_API_KEY", "").strip()
    if env_key and not db.get_setting("api_key"):
        db.set_setting("api_key", env_key)
    global _poller
    _stop_event.clear()
    _poller = threading.Thread(target=poll_loop, args=(_stop_event,), daemon=True)
    _poller.start()
    yield
    _stop_event.set()
    if _poller:
        _poller.join(timeout=2)


app = FastAPI(title="RH Studio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    db.init_db()
    return {"ok": True, **db.counts()}


@app.get("/api/settings")
def get_settings():
    api_key = db.get_setting("api_key") or os.getenv("RUNNINGHUB_API_KEY", "")
    masked = ""
    if api_key:
        masked = api_key[:4] + "*" * max(0, len(api_key) - 8) + api_key[-4:]
    return {
        "api_key": api_key,
        "api_key_masked": masked,
        "has_key": bool(api_key),
        "sample_webapp_id": SAMPLE_WEBAPP_ID,
    }


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    db.set_setting("api_key", body.api_key.strip())
    checked = False
    account = None
    message = "已保存，未校验"
    if body.api_key.strip():
        try:
            with RunningHubClient(body.api_key.strip()) as client:
                account = client.account_status()
            checked = True
            message = "已保存并校验通过"
        except RunningHubError:
            message = "已保存，未校验"
    return {"ok": True, "checked": checked, "account": account, "message": message}


@app.get("/api/tools")
def api_list_tools():
    return {"items": db.list_tools()}


@app.post("/api/tools/import")
def api_import_tool(body: ImportIn):
    if body.demo:
        webapp_id = SAMPLE_WEBAPP_ID
    else:
        raw = body.webappId or body.url or ""
        try:
            webapp_id = extract_webapp_id(raw)
        except SchemaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    tool = import_schema(webapp_id, demo=body.demo)
    return tool


@app.get("/api/tools/{tool_id}")
def api_get_tool(tool_id: int):
    tool = db.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return tool


@app.put("/api/tools/{tool_id}")
def api_update_tool(tool_id: int, body: ToolUpdateIn):
    tool = db.update_tool(tool_id, body.model_dump(exclude_none=True))
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return tool


@app.delete("/api/tools/{tool_id}")
def api_delete_tool(tool_id: int):
    if not db.delete_tool(tool_id):
        raise HTTPException(status_code=404, detail="工具不存在")
    return {"ok": True}


@app.post("/api/tools/{tool_id}/refresh")
def api_refresh_tool(tool_id: int):
    tool = db.get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return import_schema(tool["webapp_id"], demo=False)


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    digest = hashlib.sha256(content).hexdigest()
    existing = db.get_media_by_hash(digest)
    if existing and existing.get("rh_file_name"):
        return {
            "id": existing["id"],
            "fileName": existing["rh_file_name"],
            "original_name": existing["original_name"],
            "size": existing["size"],
            "reused": True,
        }
    suffix = Path(file.filename or "upload.bin").suffix
    local_name = f"{digest}{suffix}"
    local_path = db.UPLOAD_DIR / local_name
    local_path.write_bytes(content)
    try:
        with client_from_settings() as client:
            rh_name = client.upload(content, file.filename or local_name)
    except RunningHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    media = db.save_media(
        original_name=file.filename or local_name,
        local_path=str(local_path),
        rh_file_name=rh_name,
        mime_type=file.content_type or "",
        size=len(content),
        file_hash=digest,
    )
    return {
        "id": media["id"],
        "fileName": media["rh_file_name"],
        "original_name": media["original_name"],
        "size": media["size"],
        "reused": False,
    }


@app.get("/api/media/{media_id}")
def api_media(media_id: int):
    media = db.get_media(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(media["local_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="本地文件已丢失")
    return FileResponse(path, filename=media["original_name"])


@app.post("/api/tasks")
def api_create_task(body: TaskCreateIn):
    tool = db.get_tool(body.tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    try:
        nodes = build_submit_nodes(tool.get("fields") or [], body.values or {})
    except SchemaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task = db.create_task(tool["id"], tool["webapp_id"], body.instance_type, nodes)
    try:
        with client_from_settings() as client:
            result = client.run_app(tool["webapp_id"], nodes, body.instance_type)
    except RunningHubError as exc:
        db.update_task(task["id"], status="failed", error_message=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    updated = db.update_task(
        task["id"],
        rh_task_id=str(result.get("taskId") or ""),
        status="running" if str(result.get("taskStatus") or "").upper() == "RUNNING" else "queued",
        error_message="",
    )
    return updated


@app.get("/api/tasks")
def api_list_tasks():
    return {"items": db.list_tasks()}


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/api/tasks/{task_id}/cancel")
def api_cancel_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.get("rh_task_id"):
        raise HTTPException(status_code=400, detail="任务尚未提交到 RunningHub")
    try:
        with client_from_settings() as client:
            client.cancel(task["rh_task_id"])
    except RunningHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return db.update_task(task_id, status="cancelled", error_message="")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7788"))
    uvicorn.run("app:app", host=host, port=port, reload=False)
