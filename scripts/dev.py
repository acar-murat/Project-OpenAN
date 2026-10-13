#!/usr/bin/env python3
"""Local dev stack for the OpenAN energy-saving function (Linux, macOS, Windows).

    python scripts/dev.py setup            # virtualenvs + .dev/dev.env (idempotent)
    python scripts/dev.py up [SERVICE...]  # start services in the background, wait until healthy
    python scripts/dev.py status
    python scripts/dev.py logs SERVICE     # print a service's log
    python scripts/dev.py down             # stop everything started by `up`
    python scripts/dev.py test             # ruff + pytest for mocks/ and scripts/
    python scripts/dev.py demo [ARGS...]   # run scripts/demo_uc1.py against the running stack
    python scripts/dev.py ci               # setup, test, up, demo, down (what CI runs)

Services, in start order: registry (5000), orchestration (5001), price-api (8090),
mae (8091). ``designer`` (the Orchestration Center UI, 3003, needs Node) starts
only when named.

Everything generated lives in ``.dev/`` (git-ignored): one virtualenv per
service (Registry and Orchestration pin conflicting versions), logs, pid files,
and ``dev.env``. ``dev.env`` holds the settings shared by this script, the VS
Code launch configurations and the demo, including a generated Orchestration
admin password for this machine only. Registry runs in its documented local
HTTP demo profile (no TLS, signing or owner isolation); never expose these
ports beyond localhost.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / ".dev"
LOGS = DEV / "logs"
PIDS = DEV / "pids"
ENV_FILE = DEV / "dev.env"
UPSTREAM = ROOT / "upstream"
WINDOWS = os.name == "nt"

VENVS = {
    "registry-center": [UPSTREAM / "registry-center" / "requirements.txt"],
    "orchestration-center": [UPSTREAM / "orchestration-center" / "requirements.txt"],
    "mocks": [ROOT / "mocks" / "requirements.txt"],
}

SERVICES = {
    "registry": {
        "venv": "registry-center", "module": "agent_registry.start",
        "cwd": UPSTREAM / "registry-center", "health": "http://127.0.0.1:5000/rest/v1/registry-center/agent-cards",
    },
    "orchestration": {
        "venv": "orchestration-center", "module": "orchestrate.start",
        "cwd": UPSTREAM / "orchestration-center", "health": "http://127.0.0.1:5001/health",
    },
    "price-api": {"venv": "mocks", "module": "mocks.price_api", "cwd": ROOT, "health": "http://127.0.0.1:8090/health"},
    "mae": {"venv": "mocks", "module": "mocks.mae", "cwd": ROOT, "health": "http://127.0.0.1:8091/health"},
    "designer": {
        "command": ["npm", "run", "dev"], "cwd": UPSTREAM / "orchestration-center" / "workflow-designer",
        "health": "http://127.0.0.1:3003/",
    },
}
DEFAULT_SERVICES = ["registry", "orchestration", "price-api", "mae"]

# Settings shared by every service. Each process reads only the keys it knows.
BASE_ENV = {
    # Registry Center: documented local HTTP demo profile (docs/container-deployment.md upstream).
    "REGISTRY_IP": "127.0.0.1",
    "REGISTRY_PORT": "5000",
    "REGISTRY_ENABLE_HTTPS": "false",
    "REGISTRY_VERIFY_CLIENT": "false",
    "REGISTRY_OWNER_ISOLATION_ENABLED": "false",
    "REGISTRY_REGISTRY_SIGN_ENABLED": "false",
    "REGISTRY_SIGNATURE_VALIDATION_ENABLED": "false",
    # Orchestration Center over HTTP, pointed at the local registry.
    "ORCH_IP": "127.0.0.1",
    "ORCH_PORT": "5001",
    "ORCH_ENABLE_HTTPS": "false",
    "AGENT_REGISTRY_URL": "http://127.0.0.1:5000",
    "ORCH_CENTER_URL": "http://127.0.0.1:5001",
    "ORCH_AUTH_USERNAME": "admin",
    # Mocks.
    "MOCK_PRICE_HOST": "127.0.0.1",
    "MOCK_PRICE_PORT": "8090",
    "MOCK_PRICE_MODE": "normal",
    "MOCK_MAE_HOST": "127.0.0.1",
    "MOCK_MAE_PORT": "8091",
    "MOCK_MAE_SCENARIO": "auto",
    "MOCK_MAE_STEP_DELAY_SECONDS": "0.5",
    "REGISTRY_CENTER_URL": "http://127.0.0.1:5000",
    "MOCK_MAE_URL": "http://127.0.0.1:8091",
    "ENERGY_AGENT_PRICE_API_BASE_URL": "http://127.0.0.1:8090",
    "PYTHONUNBUFFERED": "1",
    "NO_PROXY": "127.0.0.1,localhost",
    "no_proxy": "127.0.0.1,localhost",
}


def venv_python(name: str) -> Path:
    venv = DEV / f"venv-{name}"
    return venv / ("Scripts/python.exe" if WINDOWS else "bin/python")


def run(command: list[str], **kwargs) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)


# setup ----------------------------------------------------------------------

def setup_venv(name: str, requirements: list[Path]) -> None:
    stamp = DEV / f"venv-{name}.stamp"
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in requirements)).hexdigest()
    if venv_python(name).exists() and stamp.exists() and stamp.read_text() == digest:
        print(f"venv-{name}: up to date")
        return
    venv = DEV / f"venv-{name}"
    uv = shutil.which("uv")
    if uv:
        run([uv, "venv", "--quiet", "--allow-existing", "--python", ">=3.12", venv])
        install = [uv, "pip", "install", "--quiet", "--python", venv_python(name)]
    else:
        run([sys.executable, "-m", "venv", venv])
        install = [venv_python(name), "-m", "pip", "install", "--quiet"]
    for path in requirements:
        run([*install, "-r", path])
    stamp.write_text(digest)


def read_env() -> dict[str, str]:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
    return values


def write_env() -> None:
    existing = read_env()
    # Values already in the file win, so local edits survive re-running setup.
    values = {**BASE_ENV, **existing}
    if not existing.get("ORCH_AUTH_PASSWORD") or not existing.get("ORCH_ACCESS_PASSWORD"):
        password = "Dev-" + secrets.token_urlsafe(12) + "#1"
        hashed = subprocess.run(
            [str(venv_python("orchestration-center")), "-c",
             "import sys; from common.util.password_hash import hash_password; print(hash_password(sys.argv[1]))",
             password],
            cwd=UPSTREAM / "orchestration-center", check=True, capture_output=True, text=True,
        ).stdout.strip()
        values["ORCH_AUTH_PASSWORD"] = password
        values["ORCH_ACCESS_PASSWORD"] = "v4:" + hashed
    lines = ["# Generated by scripts/dev.py setup. Local development only; do not commit.", ""]
    lines += [f"{key}={value}" for key, value in values.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    if not WINDOWS:
        ENV_FILE.chmod(0o600)
    print(f"wrote {ENV_FILE.relative_to(ROOT)} (Orchestration login: admin / ORCH_AUTH_PASSWORD in that file)")


def cmd_setup(_args: list[str]) -> None:
    DEV.mkdir(exist_ok=True)
    for name, requirements in VENVS.items():
        setup_venv(name, requirements)
    write_env()


# up / down / status -----------------------------------------------------------

def service_env() -> dict[str, str]:
    env = {**os.environ, **read_env()}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), env.get("PYTHONPATH")]))
    return env


def pid_of(name: str) -> int | None:
    path = PIDS / f"{name}.pid"
    if not path.exists():
        return None
    pid = int(path.read_text())
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        path.unlink(missing_ok=True)
        return None
    return pid


def healthy(url: str) -> bool:
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError):
        return False


def start(name: str, timeout: float) -> None:
    spec = SERVICES[name]
    if pid_of(name):
        print(f"{name}: already running")
        return
    if "command" in spec:
        if not (spec["cwd"] / "node_modules").exists():
            run(["npm", "install", "--force"], cwd=spec["cwd"], shell=WINDOWS)
        command = spec["command"]
    else:
        command = [str(venv_python(spec["venv"])), "-m", spec["module"]]
    LOGS.mkdir(parents=True, exist_ok=True)
    PIDS.mkdir(parents=True, exist_ok=True)
    log = (LOGS / f"{name}.log").open("w")
    flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    process = subprocess.Popen(command, cwd=spec["cwd"], env=service_env(), stdout=log,
                               stderr=subprocess.STDOUT, shell=WINDOWS and "command" in spec, **flags)
    (PIDS / f"{name}.pid").write_text(str(process.pid))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"{name} exited with code {process.returncode}; see .dev/logs/{name}.log:\n"
                             + (LOGS / f"{name}.log").read_text()[-3000:])
        if healthy(spec["health"]):
            print(f"{name}: up ({spec['health']})")
            return
        time.sleep(0.5)
    raise SystemExit(f"{name} did not become healthy within {timeout:.0f}s; see .dev/logs/{name}.log")


def stop(name: str) -> None:
    pid = pid_of(name)
    if not pid:
        return
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.25)
                os.kill(pid, 0)
            os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    (PIDS / f"{name}.pid").unlink(missing_ok=True)
    print(f"{name}: stopped")


def selected(args: list[str]) -> list[str]:
    names = [a for a in args if not a.startswith("-")] or DEFAULT_SERVICES
    unknown = [n for n in names if n not in SERVICES]
    if unknown:
        raise SystemExit(f"unknown service(s) {unknown}; choose from {list(SERVICES)}")
    return names


def wait_for_registration(timeout: float = 30) -> None:
    """The mock MAE registers in the background; wait until the Registry Center lists it."""
    url = "http://127.0.0.1:5000/rest/v1/registry-center/agent-cards/OpenAN%20Mock/Mock%20MAE"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
                if b"Mock MAE" in response.read():
                    print("mae: registered in Registry Center")
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    raise SystemExit("mae did not appear in the Registry Center; see .dev/logs/mae.log")


def cmd_up(args: list[str]) -> None:
    if not ENV_FILE.exists():
        cmd_setup([])
    for name in selected(args):
        start(name, timeout=120 if name == "designer" else 60)
        if name == "mae" and pid_of("registry"):
            wait_for_registration()


def cmd_down(_args: list[str]) -> None:
    for name in reversed(list(SERVICES)):
        stop(name)


def cmd_status(_args: list[str]) -> None:
    for name, spec in SERVICES.items():
        pid = pid_of(name)
        state = "healthy" if healthy(spec["health"]) else ("starting/unhealthy" if pid else "stopped")
        print(f"{name:14} {state:20} pid={pid or '-':<8} {spec['health']}")


def cmd_logs(args: list[str]) -> None:
    for name in selected(args):
        path = LOGS / f"{name}.log"
        print(f"==> {path.relative_to(ROOT)}")
        print(path.read_text() if path.exists() else "(no log)")


# test / demo / ci -------------------------------------------------------------

def cmd_test(_args: list[str]) -> None:
    python = venv_python("mocks")
    run([python, "-m", "ruff", "check", "mocks", "scripts"], cwd=ROOT)
    run([python, "-m", "pytest", "-q", "mocks/tests"], cwd=ROOT, env=service_env())


def cmd_demo(args: list[str]) -> None:
    run([venv_python("mocks"), ROOT / "scripts" / "demo_uc1.py", *args], cwd=ROOT, env=service_env())


def cmd_ci(_args: list[str]) -> None:
    cmd_setup([])
    cmd_test([])
    try:
        cmd_up([])
        os.environ["DEMO_REQUIRE_REGISTRY"] = "1"
        cmd_demo([])
        cmd_demo(["--scenario", "infeasible", "--skip-orchestration"])
    except BaseException:
        cmd_logs(DEFAULT_SERVICES)
        raise
    finally:
        cmd_down([])


COMMANDS = {
    "setup": cmd_setup, "up": cmd_up, "down": cmd_down, "status": cmd_status, "logs": cmd_logs,
    "test": cmd_test, "demo": cmd_demo, "ci": cmd_ci,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
