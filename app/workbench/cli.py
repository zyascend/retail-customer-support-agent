from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import uvicorn

from app.config import resolve_config
from app.workbench.api import (
    DEFAULT_AGENTOPS_ARTIFACT_DIR,
    DEFAULT_WORKBENCH_ARTIFACT_DIR,
    create_app,
)
from app.workbench.cases import build_case_catalog


def workbench_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Workbench API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--artifact-dir", default=str(DEFAULT_WORKBENCH_ARTIFACT_DIR))
    parser.add_argument(
        "--agentops-artifact-dir",
        default=str(DEFAULT_AGENTOPS_ARTIFACT_DIR),
        help="Directory containing AgentOps eval reports and trace artifacts.",
    )
    parser.add_argument("--tau3-retail-root")
    parser.add_argument("--tau2-bench-root")
    parser.add_argument("--print-config", action="store_true")
    args = parser.parse_args(argv)

    config = resolve_config(
        tau3_retail_root=args.tau3_retail_root,
        tau2_bench_root=args.tau2_bench_root,
        artifact_dir=args.artifact_dir,
    )

    if args.print_config:
        print(
            json.dumps(
                {
                    "api_url": f"http://{args.host}:{args.port}",
                    "frontend_dev_url": "http://localhost:5173",
                    "llm_available": bool(config.deepseek_api_key),
                    "agentops_artifact_dir": str(
                        Path(args.agentops_artifact_dir).expanduser().resolve()
                    ),
                    "case_catalog": build_case_catalog(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("Workbench API starting", file=sys.stderr)
    print(f"API: http://{args.host}:{args.port}", file=sys.stderr)
    print(
        "Frontend dev server: cd workbench && npm install && npm run dev",
        file=sys.stderr,
    )
    print("Then open: http://localhost:5173", file=sys.stderr)

    app = create_app(
        config=config,
        agentops_artifact_dir=Path(args.agentops_artifact_dir).expanduser().resolve(),
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(workbench_main())
