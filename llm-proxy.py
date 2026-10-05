#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm-proxy.py —— 给 optimized-chat.html 用的"本地小中转"（只用 Python 自带库，不需要 pip install 任何东西）

它干两件事：
  1. 把 optimized-chat.html 用 http://127.0.0.1:8000/ 提供出来（这样页面和接口同源，不存在跨域问题）；
  2. 提供 POST /api/chat 接口：把页面发来的对话转发给大模型，并把流式（一个字一个字回来）的数据原样转发回页面。

【为什么需要它】浏览器直接调大模型有两个坑：① 很多厂商不允许网页跨域直连；② 把 API Key 写进 HTML 等于把
家门钥匙贴在门上。有了这个小中转，Key 只存在你自己电脑的 llm-config.json 里，页面里一个字符都没有。

用法（在本文件所在目录打开 PowerShell / CMD）：
    python llm-proxy.py --mock      # 【推荐第一步】不连大模型，用假数据验证页面和流式渲染
    python llm-proxy.py             # 读取 llm-config.json，真实调用大模型
    python llm-proxy.py --port 9000 # 换端口

然后浏览器打开它打印出来的地址（默认 http://127.0.0.1:8000/ ）。
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------- 基础路径 ----------
HERE = os.path.dirname(os.path.abspath(__file__))          # 本脚本所在目录
CONFIG_PATH = os.path.join(HERE, "llm-config.json")        # 密钥/地址/模型名放这里
PAGE_NAME = ""            # 启动时自动确定，见 resolve_page()
PAGE_CANDIDATES = ["冰岩实习.html", "optimized-chat.html", "index.html"]


def resolve_page():
    """确定要托管的页面：优先候选名，其次同目录里唯一的 .html"""
    for name in PAGE_CANDIDATES:
        if os.path.isfile(os.path.join(HERE, name)):
            return name
    htmls = sorted(f for f in os.listdir(HERE) if f.lower().endswith((".html", ".htm")))
    return htmls[0] if htmls else ""

# ---------- 默认配置：改成你厂商的值即可（也可以只改 llm-config.json） ----------
DEFAULT_CONFIG = {
    # 智谱开放平台（OpenAI 兼容），免费模型适合先跑通链路
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-4-flash",
    "api_key": "",
    "system_prompt": "你是一个友好、简洁的中文助手。",
    "timeout": 120,
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def load_config():
    """读取 llm-config.json；环境变量优先级更高，方便临时切换厂商。"""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as exc:  # 配置文件写坏了也能启动，并明确告诉用户
            print(f"[警告] 读取 llm-config.json 失败：{exc}（先用默认配置启动）")
    for env_name, key in (("LLM_API_KEY", "api_key"), ("LLM_BASE_URL", "base_url"), ("LLM_MODEL", "model")):
        val = os.environ.get(env_name)
        if val:
            cfg[key] = val.strip()
    return cfg


def sse(obj):
    """把一个 JSON 对象包成 SSE 数据行（大模型流式返回用的就是这个格式）。"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def mock_lines(text):
    """--mock 模式：不联网，按 OpenAI 流式格式一个字一个字吐出来，用来单独验证页面。"""
    for ch in text:
        yield sse({"choices": [{"delta": {"content": ch}}]})
        time.sleep(0.02)
    yield "data: [DONE]\n\n"


def upstream_lines(cfg, messages):
    """真实调用：转发给厂商的 /chat/completions，逐行把流式数据读回来。"""
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,          # 关键：要流式输出
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=cfg["timeout"])
    try:
        while True:
            raw = resp.readline()          # SSE 是一行一行的事件，按行转发最稳
            if not raw:
                break
            yield raw.decode("utf-8", "replace")
    finally:
        resp.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"   # 用"关闭连接"表示流结束，最简单可靠
    server_version = "LLMProxy/1.0"

    # 让页面即使是用双击打开（file:// 来源）也能调用本接口
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    def log_message(self, fmt, *args):          # 只打一行精简日志，方便看错
        sys.stderr.write("[proxy] " + (fmt % args) + "\n")

    # ---------- 跨域预检 ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---------- 静态文件：把 optimized-chat.html 交给浏览器 ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            path = "/" + PAGE_NAME
        target = os.path.normpath(os.path.join(HERE, path.lstrip("/")))
        if not target.startswith(HERE) or not os.path.isfile(target):
            self.send_error(404, "Not Found")
            return
        with open(target, "rb") as f:
            body = f.read()
        ext = os.path.splitext(target)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    # ---------- 核心：POST /api/chat ----------
    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/chat":
            self.send_error(404, "Not Found")
            return

        # 1) 读请求体
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:
            self._json_error(400, f"请求体不是合法 JSON：{exc}")
            return

        messages = data.get("messages") or []
        if not isinstance(messages, list) or not messages:
            self._json_error(400, "messages 为空，页面没有把对话内容发过来")
            return

        # 2) 需要时在服务端补上 system 提示词（前端不用管）
        if cfg["system_prompt"] and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": cfg["system_prompt"]}] + messages

        # 3) 选数据源
        if args.mock:
            source = mock_lines("（这是 --mock 假回复）链路是通的，现在把 llm-config.json 填好就能接真模型了。")
        elif not cfg["api_key"]:
            self._json_error(400, "还没有配置 API Key：请把 llm-config.json.example 复制成 llm-config.json 并填入 api_key")
            return
        else:
            try:
                source = upstream_lines(cfg, messages)
            except urllib.error.HTTPError as exc:          # 厂商返回了 401/429/402 等
                detail = exc.read().decode("utf-8", "replace")
                self._json_error(exc.code, f"厂商接口返回 {exc.code}：{detail}")
                return
            except Exception as exc:                        # 网络不通 / 域名写错 / 超时
                self._json_error(502, f"连不上厂商接口：{exc}")
                return

        # 4) 边收边发（流式）
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")   # 先吐一个注释行，让浏览器立刻进入流式读取
            self.wfile.flush()
            for line in source:
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass   # 用户关掉页面了，正常现象
        except Exception as exc:
            try:
                self.wfile.write(sse({"error": {"message": f"转发中断：{exc}"}}).encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass
        self.close_connection = True

    # ---------- 统一的 JSON 错误响应 ----------
    def _json_error(self, code, message):
        body = json.dumps({"error": {"message": message}}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


def main():
    global args, cfg
    parser = argparse.ArgumentParser(description="本地大模型中转（给 optimized-chat.html 用）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--mock", action="store_true", help="假数据模式：不调用大模型，只验证页面与流式渲染")
    args = parser.parse_args()
    cfg = load_config()

    global PAGE_NAME
    PAGE_NAME = resolve_page()
    if not PAGE_NAME:
        print("[错误] 同目录下没找到 .html 页面，请把页面和本脚本放在同一目录。")
        return 1

    # 只绑定 127.0.0.1：局域网里的别人访问不到你的 Key
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 62)
    print(f"  页面文件： {PAGE_NAME}")
    print(f"  页面地址： {url}          ← 用浏览器打开这个（不要双击 html）")
    print(f"  接口地址： {url}api/chat")
    print(f"  运行模式： {'--mock 假数据（不调用大模型）' if args.mock else '真实调用'}")
    if not args.mock:
        key = cfg["api_key"]
        # 只报长度，不打印任何 Key 片段：避免截图/日志外发时带出半截密钥
        shown = f"已配置（长度 {len(key)} 位）" if key else "（未配置）"
        print(f"  厂商地址： {cfg['base_url']}")
        print(f"  模型名称： {cfg['model']}")
        print(f"  API Key ： {shown}")
    print("  停止服务： 在本窗口按 Ctrl + C")
    print("=" * 62)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    args = None
    cfg = {}
    sys.exit(main())
