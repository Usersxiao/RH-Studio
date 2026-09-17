from __future__ import annotations

from typing import Any
import re

import httpx

from schema import app_name_from_schema, cover_from_schema



NUXT_SPECIAL = {
    "ShallowReactive",
    "Reactive",
    "ShallowRef",
    "Ref",
    "EmptyShallowRef",
    "EmptyRef",
}


def hydrate_nuxt_payload(payload: list[Any]) -> Any:
    cache: dict[int, Any] = {}

    def resolve(node: Any) -> Any:
        if isinstance(node, bool) or node is None:
            return node
        if isinstance(node, int):
            if node < 0 or node >= len(payload):
                return node
            if node in cache:
                return cache[node]
            cache[node] = None
            cache[node] = resolve(payload[node])
            return cache[node]
        if isinstance(node, list):
            if node and isinstance(node[0], str) and node[0] in NUXT_SPECIAL and len(node) >= 2:
                return resolve(node[1])
            return [resolve(item) for item in node]
        if isinstance(node, dict):
            return {key: resolve(value) for key, value in node.items()}
        return node

    return resolve(0)


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()


def schema_from_detail(webapp_id: str, detail: dict[str, Any], source: str) -> dict[str, Any]:
    nodes = detail.get("inputNodes") or detail.get("nodeInfoList") or []
    covers = detail.get("covers") or []
    cover_url = ""
    if isinstance(covers, list) and covers and isinstance(covers[0], dict):
        cover_url = str(covers[0].get("url") or covers[0].get("thumbnailUri") or "")
    if not cover_url:
        cover_url = cover_from_schema(detail)
    name = app_name_from_schema(detail, str(detail.get("name") or f"App {webapp_id}"))
    return {
        "webappId": str(detail.get("id") or webapp_id),
        "name": name,
        "cover_url": cover_url,
        "description": _strip_html(str(detail.get("description") or "")),
        "statistics": detail.get("statisticsInfo") or {},
        "nodeInfoList": nodes,
        "raw": detail,
        "empty_nodes": not bool(nodes),
        "source": source,
    }


def fetch_public_webapp_schema(webapp_id: str) -> dict[str, Any]:
    url = f"https://www.runninghub.cn/ai-detail/{webapp_id}/_payload.json"
    with httpx.Client(timeout=30.0, headers={"User-Agent": "RH-Studio/1.0"}) as client:
        response = client.get(url)
    try:
        payload = response.json()
    except Exception as exc:
        raise RunningHubError(
            f"\u516c\u5f00\u9875\u8fd4\u56de\u4e86\u65e0\u6cd5\u89e3\u6790\u7684\u54cd\u5e94\uff1a{response.text[:200]}",
            status_code=response.status_code,
        ) from exc
    if response.status_code >= 400 or not isinstance(payload, list):
        raise RunningHubError(
            f"\u65e0\u6cd5\u4ece\u516c\u5f00\u9875\u62c9\u53d6\u5e94\u7528 {webapp_id} \u7684\u53c2\u6570",
            payload if isinstance(payload, dict) else {"data": payload},
            response.status_code,
        )
    root = hydrate_nuxt_payload(payload)
    data = root.get("data") if isinstance(root, dict) else {}
    detail = None
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get("detail"), dict):
                detail = value["detail"]
                break
            if isinstance(value, dict) and (value.get("inputNodes") or value.get("nodeInfoList")):
                detail = value
                break
    if not isinstance(detail, dict):
        raise RunningHubError(f"\u516c\u5f00\u9875\u6ca1\u6709\u8fd4\u56de\u5e94\u7528 {webapp_id} \u7684\u53c2\u6570")
    return schema_from_detail(webapp_id, detail, "public")


def fetch_webapp_schema(webapp_id: str, api_key: str | None = None) -> dict[str, Any]:
    public_error = None
    try:
        public_schema = fetch_public_webapp_schema(webapp_id)
        if not api_key or public_schema.get("nodeInfoList"):
            return public_schema
    except RunningHubError as exc:
        public_error = exc
        public_schema = None
    if api_key:
        with RunningHubClient(api_key) as client:
            official = client.get_webapp_schema(webapp_id)
        official["source"] = "api"
        if official.get("nodeInfoList") or public_schema is None:
            return official
        return public_schema
    if public_error:
        raise public_error
    raise RunningHubError("\u65e0\u6cd5\u83b7\u53d6\u5e94\u7528\u53c2\u6570")

class RunningHubError(RuntimeError):
    def __init__(self, message: str, payload: dict[str, Any] | None = None, status_code: int | None = None):
        super().__init__(message)
        self.payload = payload or {}
        self.status_code = status_code


class RunningHubClient:
    def __init__(self, api_key: str, timeout: float = 60.0):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise RunningHubError("请先在设置里填写 RunningHub API Key")
        self.client = httpx.Client(
            base_url="https://www.runninghub.cn",
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "RunningHubClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise RunningHubError(f"RunningHub 返回了无法解析的响应：{response.text[:300]}", status_code=response.status_code) from exc
        if not isinstance(payload, dict):
            raise RunningHubError("RunningHub 返回格式异常", {"data": payload}, response.status_code)
        return payload

    def get_webapp_schema(self, webapp_id: str) -> dict[str, Any]:
        response = self.client.get(
            "/api/webapp/apiCallDemo",
            params={"apiKey": self.api_key, "webappId": webapp_id},
        )
        payload = self._json(response)
        if payload.get("code") != 0:
            raise RunningHubError(payload.get("msg") or "获取应用参数失败", payload, response.status_code)
        data = payload.get("data") or {}
        nodes = data.get("nodeInfoList") or []
        return {
            "webappId": str(webapp_id),
            "name": app_name_from_schema(data, f"App {webapp_id}"),
            "cover_url": cover_from_schema(data),
            "statistics": data.get("statisticsInfo") or {},
            "nodeInfoList": nodes,
            "raw": data,
            "empty_nodes": not bool(nodes),
        }

    def upload(self, content: bytes, filename: str, file_type: str = "input") -> str:
        response = self.client.post(
            "/task/openapi/upload",
            data={"apiKey": self.api_key, "fileType": file_type},
            files={"file": (filename, content)},
            timeout=120.0,
        )
        payload = self._json(response)
        if payload.get("code") != 0:
            raise RunningHubError(payload.get("msg") or "上传文件失败", payload, response.status_code)
        data = payload.get("data") or {}
        file_name = data.get("fileName") if isinstance(data, dict) else None
        if not file_name:
            raise RunningHubError("上传成功但未返回 fileName", payload, response.status_code)
        return str(file_name)

    def run_app(self, webapp_id: str, node_info_list: list[dict[str, str]], instance_type: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "apiKey": self.api_key,
            "webappId": int(webapp_id) if str(webapp_id).isdigit() else webapp_id,
            "nodeInfoList": node_info_list,
        }
        if instance_type and instance_type != "default":
            body["instanceType"] = instance_type
        response = self.client.post("/task/openapi/ai-app/run", json=body)
        payload = self._json(response)
        if payload.get("code") != 0:
            raise RunningHubError(payload.get("msg") or "发起任务失败", payload, response.status_code)
        data = payload.get("data") or {}
        task_id = data.get("taskId") if isinstance(data, dict) else None
        if not task_id:
            raise RunningHubError("任务已提交但未返回 taskId", payload, response.status_code)
        return data

    def query_outputs(self, task_id: str) -> dict[str, Any]:
        response = self.client.post(
            "/task/openapi/outputs",
            json={"apiKey": self.api_key, "taskId": task_id},
        )
        return self._json(response)

    def cancel(self, task_id: str) -> dict[str, Any]:
        response = self.client.post(
            "/task/openapi/cancel",
            json={"apiKey": self.api_key, "taskId": task_id},
        )
        payload = self._json(response)
        if payload.get("code") != 0:
            raise RunningHubError(payload.get("msg") or "取消任务失败", payload, response.status_code)
        return payload

    def account_status(self) -> dict[str, Any]:
        response = self.client.post(
            "/uc/openapi/accountStatus",
            json={"apiKey": self.api_key},
        )
        payload = self._json(response)
        if payload.get("code") != 0:
            raise RunningHubError(payload.get("msg") or "校验 API Key 失败", payload, response.status_code)
        return payload.get("data") or payload


def interpret_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code")
    data = payload.get("data")
    if code == 0:
        files = []
        if isinstance(data, list):
            files = data
        elif isinstance(data, dict):
            files = data.get("results") or data.get("outputs") or ([data] if data.get("fileUrl") else [])
        return {"status": "success", "status_code": code, "outputs": files, "error": ""}
    if code == 804:
        return {"status": "running", "status_code": code, "outputs": [], "error": ""}
    if code == 813:
        return {"status": "queued", "status_code": code, "outputs": [], "error": ""}
    reason = payload.get("failedReason") or payload.get("msg") or f"未知状态码 {code}"
    if isinstance(data, dict):
        reason = data.get("failedReason") or data.get("errorMessage") or reason
    if code == 805:
        return {"status": "failed", "status_code": code, "outputs": [], "error": str(reason)}
    return {"status": "failed", "status_code": code, "outputs": [], "error": str(reason)}
