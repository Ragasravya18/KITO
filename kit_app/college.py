from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .settings import COLLEGE_API, PARTICIPANT_KEY

VISITOR_PATHS = {"/v1/college", "/v1/courses", "/v1/today", "/v1/documents", "/v1/placements/drives"}
WRITES = {("post", "/v1/admissions/applications"), ("post", "/v1/me/requests"), ("post", "/v1/placements/drives/{drive_id}/register"), ("post", "/v1/teacher/requests/{request_id}/approve"), ("post", "/v1/teacher/requests/{request_id}/reject")}


class CollegeClient:
    def __init__(self):
        self.spec: dict[str, Any] | None = None
        self.tools: dict[str, dict[str, Any]] = {}

    async def request(self, method: str, path: str, session: dict | None = None, *, params=None, body=None, idempotency_key=None):
        if not PARTICIPANT_KEY:
            raise RuntimeError("KIT_PARTICIPANT_KEY is not configured on the server.")
        headers = {"X-Participant-Key": PARTICIPANT_KEY}
        if session and session.get("token"):
            headers["Authorization"] = f"Bearer {session['token']}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=18) as client:
            response = await client.request(method, COLLEGE_API + path, headers=headers, params=params, json=body)
        try:
            data = response.json()
        except ValueError:
            data = {"error": {"message": response.text[:300]}}
        if response.is_error:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            raise RuntimeError(error.get("message", f"College service returned {response.status_code}"))
        return data

    async def login(self, login_id: str, password: str):
        return await self.request("POST", "/v1/auth/login", body={"login_id": login_id, "password": password})

    async def load_tools(self):
        if self.tools:
            return list(self.tools.values())
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(COLLEGE_API + "/openapi.json", headers={"X-Participant-Key": PARTICIPANT_KEY} if PARTICIPANT_KEY else {})
                r.raise_for_status()
                self.spec = r.json()
        except Exception:
            self.spec = {"paths": {}}
        paths = self.spec.get("paths", {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                method = method.lower()
                if method not in {"get", "post", "patch", "put", "delete"} or not path.startswith("/v1/"):
                    continue
                if path.startswith("/v1/auth/") or path.startswith("/v1/documents/{document_id}/file"):
                    continue
                op_id = operation.get("operationId") or f"{method}_{path}"
                name = re.sub(r"[^a-zA-Z0-9_]", "_", op_id)[:60]
                props, required = {}, []
                for param in operation.get("parameters", []):
                    if param.get("in") in {"query", "path"}:
                        p = param.get("schema", {"type": "string"})
                        props[param["name"]] = {k: v for k, v in p.items() if k in {"type", "enum", "description"}}
                        if param.get("required"):
                            required.append(param["name"])
                request_schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                body_schema = self._resolve(request_schema)
                if body_schema.get("type") == "object":
                    for key, value in body_schema.get("properties", {}).items():
                        props[key] = {k: v for k, v in value.items() if k in {"type", "enum", "description", "format", "items"}}
                    required.extend(body_schema.get("required", []))
                self.tools[name] = {"type": "function", "function": {"name": name, "description": (operation.get("summary") or operation.get("description") or op_id)[:300], "parameters": {"type": "object", "properties": props, "required": list(dict.fromkeys(required)), "additionalProperties": False}}}
                self.tools[name]["_operation"] = {"method": method, "path": path}
        return list(self.tools.values())

    def _resolve(self, schema):
        if not isinstance(schema, dict): return {}
        ref = schema.get("$ref")
        if ref and self.spec:
            node = self.spec
            for part in ref.lstrip("#/").split("/"):
                node = node.get(part, {})
            return {**node, **{k: v for k, v in schema.items() if k != "$ref"}}
        return schema

    def role_allowed(self, role: str, method: str, path: str) -> bool:
        if path in VISITOR_PATHS:
            return True
        if path.startswith("/v1/me/") or path == "/v1/me":
            return role in {"student", "teacher"}
        if path.startswith("/v1/teacher/"):
            return role == "teacher"
        if path.startswith("/v1/placements/"):
            return role in {"student", "teacher"} or path == "/v1/placements/drives"
        return False

    async def execute_read(self, name: str, args: dict, session: dict):
        tool = self.tools.get(name)
        if not tool: raise RuntimeError("That college service is not available.")
        op = tool["_operation"]
        path = op["path"]
        if not self.role_allowed(session["role"], op["method"], path):
            raise RuntimeError("You do not have access to that college information.")
        path_args = {}
        for key in re.findall(r"\{([^}]+)\}", path):
            candidates = [key, key.removesuffix("_id"), key.replace("_", "")]
            found = next((args.pop(c) for c in candidates if c in args), None)
            if found is None: raise RuntimeError(f"I need {key.replace('_', ' ')} to do that.")
            path_args[key] = found
        for key, value in path_args.items(): path = path.replace("{" + key + "}", str(value))
        if op["method"] != "get": raise RuntimeError("This action needs a confirmation before it can be sent.")
        params = {k: v for k, v in args.items() if k not in {"body"}}
        return await self.request(op["method"].upper(), path, session, params=params)


college = CollegeClient()
