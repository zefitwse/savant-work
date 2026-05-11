"""
coursework_savant/reconfigure_listener.py
任务十二：Savant 节点端的配置接收钩子

集成方式：
    在 coursework_savant/savant_pipeline.py 的 PyFunc 中，
    启动一个后台线程运行 ReconfigureListener，
    或直接在 process_frame 中检查内存中的 latest_command。

示例：
    from coursework_savant.reconfigure_listener import ReconfigureListener
    listener = ReconfigureListener(port=50051)
    listener.start()  # 后台线程

    # 在 process_frame 中：
    if listener.latest_command:
        self.apply_command(listener.latest_command)
        listener.latest_command = None
"""
import json
import threading
import time
from typing import Optional, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler

class CommandHandler(BaseHTTPRequestHandler):
    latest_command: Optional[dict] = None

    def log_message(self, format, *args):
        # 静默日志，避免污染 Savant 输出
        pass

    def do_post(self):
        if self.path == "/internal/reconfigure":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                CommandHandler.latest_command = json.loads(body.decode())
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "accepted",
                    "command_type": CommandHandler.latest_command.get("command_type")
                }).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "detail": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_get(self):
        if self.path == "/internal/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            # 实际应由 Savant PyFunc 注入真实状态
            status = {
                "node_id": "savant-gpu-local",
                "current_model": "yolov8n.engine",
                "stream_count": 1,
                "gpu_util": 0.65,
                "latest_command": CommandHandler.latest_command,
            }
            self.wfile.write(json.dumps(status).encode())
        else:
            self.send_response(404)
            self.end_headers()

class ReconfigureListener:
    """在 Savant 容器内运行的轻量级 HTTP 服务，接收配置中心指令"""
    def __init__(self, port: int = 50051):
        self.port = port
        self.server = HTTPServer(("0.0.0.0", port), CommandHandler)
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[ReconfigureListener] HTTP server started on port {self.port}")

    def stop(self):
        self.server.shutdown()

    @property
    def latest_command(self) -> Optional[dict]:
        return CommandHandler.latest_command

    def consume_command(self) -> Optional[dict]:
        """取出并清空最新指令（在 process_frame 中调用）"""
        cmd = CommandHandler.latest_command
        CommandHandler.latest_command = None
        return cmd
