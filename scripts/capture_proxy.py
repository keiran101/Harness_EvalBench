#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capture_proxy.py — 统一 LLM 反向代理，逐请求落盘「真实输入 context」。

用途
----
在真实 LLM 端点（默认 8.134.63.180:7010）前放一个 logging 代理，让 PI / OpenCode /
DeepSeek(dsh) 三个 harness 的 base_url 全部指向它。代理把每一次
`/v1/chat/completions` 请求的完整 body（system + messages + tools）逐字落盘，
这就是 harness 实际喂给 LLM 的 context 真值。响应体也一并记录（便于 context→决策
关联）。

接线方式（零改 harness 代码）
---------------------------
三个 harness 的 base_url 都由 env `LLM_EVAL_BASE_URL` 驱动，且都会自行在末尾补
`/v1`。因此把该 env 设成下面带路径前缀的地址即可，前缀用来给捕获打 harness / task 标签：

    PI        : LLM_EVAL_BASE_URL=http://127.0.0.1:8899/pi/<task_id>
    OpenCode  : LLM_EVAL_BASE_URL=http://127.0.0.1:8899/oc/<task_id>
    DeepSeek  : LLM_EVAL_BASE_URL=http://127.0.0.1:8899/dsh/<task_id>

代理会把 `/<prefix>/v1/chat/completions` 重写回上游的 `/v1/chat/completions`，
并用 prefix 段作为 harness（及可选 task）标签。不带前缀的请求按 unknown 处理。

落盘布局
--------
<OUT_ROOT>/<harness>/<task>/<seq>_<timestamp>.json
<OUT_ROOT>/<harness>/<task>/manifest.jsonl      # 每行一条索引，便于聚合

每条记录：
    { harness, task, turn_seq, timestamp,
      request:  { model, messages, tools, temperature, max_tokens, stream, ... },
      response: { raw / parsed },
      request_chars, request_tokens_est }

环境变量
--------
    CAPTURE_UPSTREAM  上游地址，默认 8.134.63.180:7010
    CAPTURE_PORT      监听端口，默认 8899
    CAPTURE_OUT       输出根目录，默认 D:\\dev\\eval\\results\\context_capture
    CAPTURE_RESP_MAX  单条响应记录上限（字节），默认 200000，超出只记长度

注意
----
- 使用 HTTP/1.0，逐响应关闭连接，规避 chunked 复杂度；对 OpenAI 客户端透明。
- 流式(SSE)响应按原始字节透传并整体记录；非流式则解析 JSON 记录。
- 串行调用真实端点即可，无需并发；代理本身线程安全（写文件加锁）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client

UPSTREAM = os.environ.get("CAPTURE_UPSTREAM", "8.134.63.180:7010")
PORT = int(os.environ.get("CAPTURE_PORT", "8899"))
RESP_MAX = int(os.environ.get("CAPTURE_RESP_MAX", "200000"))


def _norm_path(p: str) -> str:
    """归一化路径：兼容 Git Bash 的 /d/dev/eval 写法，落到正确 Windows 位置。"""
    p = os.path.expanduser(p)
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)
    if m:                      # /d/dev/eval -> D:/dev/eval
        p = m.group(1) + ":/" + m.group(2)
    return os.path.abspath(p)


OUT_ROOT = _norm_path(os.environ.get("CAPTURE_OUT", r"D:\dev\eval\results\context_capture"))

KNOWN_HARNESS = {"pi", "oc", "opencode", "dsh"}
_lock = threading.Lock()
_seq = 0
_seq_to_fpath = {}


def _est_tokens(text: str) -> int:
    # 粗略估算：中文/代码按 ~4 字符/token，足够看 context 膨胀趋势
    return max(1, len(text) // 4)


def _split_path(path: str):
    """从请求路径解析 (harness, task, upstream_path)。"""
    parts = [p for p in path.split("/") if p]
    harness, task = "unknown", "na"
    i = 0
    if parts and parts[0] in KNOWN_HARNESS:
        harness = parts[0]
        i = 1
        if len(parts) > i and parts[i] not in ("v1", "models"):
            task = parts[i]
            i += 1
    rest = parts[i:]
    if not rest or rest[0] not in ("v1", "models"):
        # 兜底：保证以 /v1 或 /models 开头
        rest = (["v1"] + rest) if rest else ["v1", "chat", "completions"]
    upstream_path = "/" + "/".join(rest)
    return harness, task, upstream_path


def _write_capture(harness, task, req_obj, req_raw, resp_raw, req_chars):
    """落盘一条捕获。resp_raw 可为 None（仅记录请求、尚未拿到响应）。"""
    global _seq
    with _lock:
        _seq += 1
        seq = _seq
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    out_dir = os.path.join(OUT_ROOT, harness, task)
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{seq:06d}_{ts}.json"
    fpath = os.path.join(out_dir, fname)

    if resp_raw is None:
        resp_obj = None
        resp_field = None
    else:
        try:
            resp_obj = json.loads(resp_raw.decode("utf-8"))
        except Exception:
            resp_obj = None
        resp_field = (resp_obj if resp_obj is not None
                      else {"_raw": resp_raw.decode("utf-8", "replace")[:RESP_MAX],
                            "_truncated": len(resp_raw) > RESP_MAX})

    record = {
        "harness": harness,
        "task": task,
        "turn_seq": seq,
        "timestamp": ts,
        "request": req_obj if isinstance(req_obj, dict) else {"_raw": req_raw.decode("utf-8", "replace")},
        "response": resp_field,
        "request_chars": req_chars,
        "request_tokens_est": _est_tokens(req_raw.decode("utf-8", "replace")),
    }
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        with _lock:
            _seq_to_fpath[seq] = fpath
        # 索引行
        with open(os.path.join(out_dir, "manifest.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "seq": seq, "file": fname, "harness": harness, "task": task,
                "ts": ts, "req_chars": req_chars,
                "req_tokens_est": record["request_tokens_est"],
                "has_response": resp_raw is not None,
                "n_messages": len(record["request"].get("messages", [])) if isinstance(record["request"], dict) else None,
                "n_tools": len(record["request"].get("tools", [])) if isinstance(record["request"], dict) else None,
            }, ensure_ascii=False) + "\n")
        sys_print(f"[write] {fpath}")
    except Exception as e:
        sys_print(f"[write-FAIL] {fpath} :: {e!r}")
        traceback.print_exc()
    return seq


def _patch_response(harness, task, seq, resp_raw):
    with _lock:
        fpath = _seq_to_fpath.get(seq)
    if not fpath or not os.path.exists(fpath):
        sys_print(f"[patch-FAIL] seq={seq} fpath missing")
        return
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            rec = json.load(f)
    except Exception as e:
        sys_print(f"[patch-read-FAIL] {fpath} :: {e!r}")
        return
    try:
        resp_obj = json.loads(resp_raw.decode("utf-8"))
    except Exception:
        resp_obj = None
    rec["response"] = (resp_obj if resp_obj is not None
                       else {"_raw": resp_raw.decode("utf-8", "replace")[:RESP_MAX],
                             "_truncated": len(resp_raw) > RESP_MAX})
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        sys_print(f"[patched] {fpath} bytes={len(resp_raw)}")
    except Exception as e:
        sys_print(f"[patch-write-FAIL] {fpath} :: {e!r}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # 逐响应关闭，规避 chunked

    def log_message(self, *args):  # 静默默认访问日志
        return

    def _forward(self, method: str):
        harness, task, upstream_path = _split_path(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""

        try:
            req_obj = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            req_obj = None

        # 先落盘请求（保证拿到 context，即使上游挂掉/连接被重置）
        seq = _write_capture(harness, task, req_obj, body, None, len(body))
        sys_print(f"[capture] {method} {self.path} -> harness={harness} task={task} seq={seq} bytes={len(body)}")

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}

        raw = None
        try:
            conn = http.client.HTTPConnection(UPSTREAM, timeout=300)
            try:
                conn.request(method, upstream_path, body=body, headers=headers)
                resp = conn.getresponse()
                chunks = []
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() in ("transfer-encoding", "content-length"):
                        continue
                    self.send_header(k, v)
                self.end_headers()
                while True:
                    c = resp.read(8192)
                    if not c:
                        break
                    chunks.append(c)
                    try:
                        self.wfile.write(c)
                    except Exception:
                        break  # 客户端已断开，停止回写
                raw = b"".join(chunks)
            finally:
                conn.close()
        except Exception as e:
            sys_print(f"[forward-fail] seq={seq} :: {e!r}")

        if raw is not None:
            _patch_response(harness, task, seq, raw)

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        # 转发 GET（如 /v1/models），不落盘 context
        _, _, upstream_path = _split_path(self.path)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}
        conn = http.client.HTTPConnection(UPSTREAM, timeout=30)
        try:
            conn.request("GET", upstream_path, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in ("transfer-encoding", "content-length"):
                    continue
                self.send_header(k, v)
            self.end_headers()
            while True:
                c = resp.read(8192)
                if not c:
                    break
                self.wfile.write(c)
        finally:
            conn.close()


def sys_print(s: str):
    print(s, flush=True)


def main():
    os.makedirs(OUT_ROOT, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys_print(f"capture_proxy listening on 127.0.0.1:{PORT} -> upstream {UPSTREAM}")
    sys_print(f"capture out: {OUT_ROOT}")
    sys_print(f"tag harnesses via path prefix: /pi /oc /dsh  (e.g. http://127.0.0.1:{PORT}/pi/<task_id>)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys_print("shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
