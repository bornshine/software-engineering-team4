from __future__ import annotations

import argparse
from pathlib import Path
import yaml

from orchestrator.engine import OrchestratorEngine
from orchestrator.server import OrchestratorHTTPServer


def main() -> None:
    parser = argparse.ArgumentParser(description="2D/轻2.5D 游戏多 Agent 编排器与可视化控制平台")
    parser.add_argument("--host", default="127.0.0.1", help="监听主机 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认 8000)")
    parser.add_argument("--config", default="orchestrator_runtime.yaml", help="运行配置文件路径")
    parser.add_argument("--mock", action="store_true", help="强制使用确定性 Mock Worker（无外部 API Key 演示模式）")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = base_dir / cfg_path
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    engine = OrchestratorEngine(cfg, base_dir=base_dir, force_mock=args.mock)

    # 若尚未加载任何项目，则默认预加载 fixtures/handoff/xiyou-nverguo/v1.0.0 至 G1 待确认状态
    default_v1 = base_dir / "fixtures" / "handoff" / "xiyou-nverguo" / "v1.0.0"
    if not engine.list_projects() and default_v1.exists():
        engine.load_project(default_v1)

    frontend_dir = base_dir / "frontend"
    srv = OrchestratorHTTPServer((args.host, args.port), engine, frontend_dir)
    mode_tag = "MOCK 仿真模式" if engine.is_mock_mode() else "API+CLI 生产模式"
    print(f"Orchestrator server running at http://{args.host}:{args.port} [{mode_tag}]")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    main()
