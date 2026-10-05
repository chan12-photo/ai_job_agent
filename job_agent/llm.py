"""One local Ollama adapter; no remote endpoint, proxy, or cloud fallback."""

import json
import socket
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:11434"
OPTIONS = {"temperature": 0, "num_ctx": 4096, "num_predict": 768}


class LocalModelError(Exception):
    pass


class ModelTimeout(LocalModelError):
    pass


class WorkflowTimeout(ModelTimeout):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class OllamaClient:
    def __init__(self, model: str, timeout: int = 120):
        if not model or not model.strip():
            raise ValueError("모델 이름을 지정해 주세요")
        if not 1 <= timeout <= 300:
            raise ValueError("timeout은 1~300초여야 합니다")
        self.model = model
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.runtime_version = None

    def _request(self, path: str, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            BASE_URL + path, data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="GET" if data is None else "POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.url != BASE_URL + path:
                    raise LocalModelError("로컬 서버의 redirect를 허용하지 않습니다")
                raw = response.read(2 * 1024 * 1024 + 1)
        except (TimeoutError, socket.timeout) as exc:
            raise ModelTimeout("로컬 모델 요청 시간이 초과됐습니다") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ModelTimeout("로컬 모델 요청 시간이 초과됐습니다") from exc
            raise LocalModelError("로컬 Ollama 서버에 연결하지 못했거나 시간이 초과됐습니다") from exc
        if len(raw) > 2 * 1024 * 1024:
            raise LocalModelError("로컬 모델 응답이 너무 큽니다")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LocalModelError("로컬 서버 응답이 JSON이 아닙니다") from exc

    def local_models(self):
        response = self._request("/api/tags")
        if type(response) is not dict or type(response.get("models")) is not list:
            raise LocalModelError("로컬 모델 목록 형식이 맞지 않습니다")
        return response["models"]

    def complete(self, messages, schema):
        model_info = next((entry for entry in self.local_models()
                           if type(entry) is dict and entry.get("name") == self.model), None)
        if model_info is None:
            raise LocalModelError(f"로컬에 설치된 모델이 없습니다: {self.model}")
        if self.runtime_version is None:
            version = self._request("/api/version")
            if type(version) is not dict or type(version.get("version")) is not str:
                raise LocalModelError("로컬 Ollama 버전을 확인할 수 없습니다")
            self.runtime_version = version["version"]
        response = self._request("/api/chat", {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": OPTIONS,
        })
        if type(response) is not dict or response.get("done") is not True:
            raise LocalModelError("모델 응답이 완료되지 않았습니다")
        message = response.get("message")
        if type(message) is not dict or type(message.get("content")) is not str:
            raise LocalModelError("모델 응답 본문이 없습니다")
        return {
            "content": message["content"],
            "model": response.get("model"),
            "model_digest": model_info.get("digest"),
            "runtime_version": self.runtime_version,
            "quantization": model_info.get("details", {}).get("quantization_level"),
            "total_duration_ns": response.get("total_duration"),
            "load_duration_ns": response.get("load_duration"),
            "prompt_tokens": response.get("prompt_eval_count"),
            "output_tokens": response.get("eval_count"),
            "options": dict(OPTIONS),
            "think": False,
        }
