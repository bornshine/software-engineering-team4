from __future__ import annotations

import argparse
from pathlib import Path
from backend.server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="2D/2.5D 游戏开发任务动态编排与多 Agent 可视化平台")
    parser.add_argument("--host", default="127.0.0.1", help="绑定监听地址")
    parser.add_argument("--port", type=int, default=8000, help="绑定端口")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent
    server = create_server(root_dir, host=args.host, port=args.port)
    print(f"[RJGC-Agent] 2D/2.5D Game SE Workflow Platform running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[RJGC-Agent] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
