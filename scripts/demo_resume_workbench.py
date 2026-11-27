"""Local synthetic UI demo, isolated from all personal databases and model keys.

Run after installing .[workbench] and building frontend/, or use the packaged build.
"""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository


# Public, synthetic demo access code. Never used by the private workspace launcher.
DEMO_CODE = "job-agent-synthetic-demo-only-2026"
SECOND_DEMO_CODE = "job-agent-second-demo-user-2026"


def build_demo_app(path: Path,*,worker_enabled=True):
    return create_resume_app(
        SqliteResumeRepository(path), resolve_identity={DEMO_CODE: "synthetic-demo-user",SECOND_DEMO_CODE:"synthetic-second-user"}.get,
        frontend_dir=REPO / "frontend/dist", demo_only=True,
        task_worker_enabled=worker_enabled,
    )


if __name__ == "__main__":
    import argparse
    import uvicorn
    options = argparse.ArgumentParser(description="Isolated synthetic resume demo")
    options.add_argument("--port", type=int, default=8012)
    options.add_argument('--persistent',action='store_true',help='Keep synthetic data across restarts in output/demo-v3/')
    options.add_argument('--no-worker',action='store_true',help='Keep queued synthetic tasks for local restart/fault verification')
    options.add_argument('--host',choices=['127.0.0.1','0.0.0.0'],default='127.0.0.1')
    options.add_argument('--seed',action='store_true',help='Load packaged synthetic/public demo project fixtures; persistent mode only')
    args=options.parse_args()
    if args.seed and not args.persistent:options.error('--seed requires --persistent')
    port = args.port
    if not 1 <= port <= 65535:
        options.error("port must be between 1 and 65535")
    if not (REPO / "frontend/dist/index.html").is_file():
        raise SystemExit("Build frontend first: cd frontend; npm ci --ignore-scripts; npm run build")
    temporary_root = (REPO / "output/demo-tmp").resolve()
    temporary_root.mkdir(parents=True, exist_ok=True)
    if args.persistent:
        if args.seed:
            from scripts.seed_v3_demo import seed
            seed()
        database=REPO/'output/demo-v3/workspace.sqlite'
        print(f'Synthetic persistent demo: http://127.0.0.1:{port}/\nPublic access code: '+DEMO_CODE,flush=True)
        print('Synthetic data persists across restarts. No model configured. Do not upload private material.',flush=True)
        app=build_demo_app(database,worker_enabled=not args.no_worker)
        app.state.synthetic_persistent=True
        uvicorn.run(app,host=args.host,port=port,access_log=False)
        raise SystemExit(0)
    with TemporaryDirectory(prefix="synthetic-m2-", dir=temporary_root) as directory:
        if not Path(directory).resolve().is_relative_to(temporary_root):
            raise RuntimeError("unsafe_demo_directory")
        print(f"Synthetic demo: http://127.0.0.1:{port}/\nPublic demo access code: " + DEMO_CODE, flush=True)
        print("Do not upload personal material. No model is configured; demo data is temporary.", flush=True)
        uvicorn.run(build_demo_app(Path(directory) / "workspace.sqlite",worker_enabled=not args.no_worker), host=args.host, port=port, access_log=False)
