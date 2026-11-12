"""CR 统一接口的最小客户端（仅 Python 标准库）。流程见 docs/开发对接说明.md。"""
import json
import time
import urllib.error
import urllib.request
import uuid

BASE = "https://api.creative-reasoning.com"
GENERATE = "/unified/v1/images/tasks"      # 生成图片（参考图可选）
EDIT = "/unified/v1/images/edit-tasks"     # 编辑图片（参考图必填）


class CRError(Exception):
    pass


class CRClient:
    def __init__(self, api_key, base=BASE):
        self.key, self.base = api_key, base

    def _call(self, method, path, body=None, headers=None, timeout=60):
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", **(headers or {})}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), dict(e.headers)

    def submit(self, body, endpoint=GENERATE, idempotency_key=None):
        """提交任务，返回 (task, usage_id)。网络异常时用同一幂等键重试，不会重复扣费。"""
        key = idempotency_key or str(uuid.uuid4())
        for attempt in range(4):
            try:
                code, res, hdr = self._call("POST", endpoint, body, {"Idempotency-Key": key}, timeout=120)
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        if code not in (200, 202):
            raise CRError(f"HTTP {code}: {res.get('error', res)}")
        usage = hdr.get("x-cr-usage-id") or hdr.get("X-Cr-Usage-Id")
        return res, usage

    def wait(self, task_id, timeout=600):
        """等待任务到终态，返回任务正文（status 为 completed / failed）。"""
        deadline = time.monotonic() + timeout
        res = {"status": "pending"}
        while res.get("status") in ("pending", "processing"):
            if time.monotonic() > deadline:
                raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内完成，稍后用同一 ID 查询")
            try:
                code, res, _ = self._call("GET", f"/unified/v1/tasks/{task_id}/wait", timeout=40)
                if code == 429:
                    time.sleep(2)
                    code, res, _ = self._call("GET", f"/unified/v1/tasks/{task_id}", timeout=40)
            except OSError:
                time.sleep(2)
        return res

    @staticmethod
    def download(url, path):
        urllib.request.urlretrieve(url, path)
