import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import webview

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_BUNDLED = bool(getattr(sys, "frozen", False))


def _is_apple_silicon_hardware() -> bool:
    """Detect M-series hardware regardless of whether the current Python
    is running as arm64 or x86_64 (under Rosetta). `platform.machine()`
    reflects the process arch, not the host, so we shell out to sysctl."""
    if not IS_MAC:
        return False
    try:
        r = subprocess.run(
            ["sysctl", "-n", "hw.optional.arm64"],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip() == "1"
    except Exception:
        return False


IS_APPLE_SILICON = _is_apple_silicon_hardware()

if IS_BUNDLED:
    ROOT = Path(sys._MEIPASS).resolve() if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent.resolve()
else:
    ROOT = Path(__file__).parent.resolve()

VENV_PY = ROOT / "venv" / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python3")
REQS = ROOT / "requirements.txt"
SETUP_HTML = ROOT / "templates" / "setup.html"
PORT = 8765
SERVER_URL = f"http://127.0.0.1:{PORT}"

CORE_IMPORTS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "jinja2": "jinja2",
    "instaloader": "instaloader",
    "yt-dlp": "yt_dlp",
    "openai-whisper": "whisper",
}

_SUBPROCESS_FLAGS = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def arch_pinned_cmd(cmd: list) -> list:
    """On Apple Silicon, pin arm64 so subprocesses don't fall back to the x86_64
    slice of universal Python binaries (which causes arch mismatches with
    arm64-built wheels like pydantic_core)."""
    if IS_APPLE_SILICON:
        return ["arch", "-arm64"] + [str(c) for c in cmd]
    return [str(c) for c in cmd]


def brew_aware_path() -> list[str]:
    sep = ";" if IS_WINDOWS else ":"
    paths = os.environ.get("PATH", "").split(sep)
    if IS_MAC:
        for p in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin"):
            if p not in paths and Path(p).exists():
                paths.insert(0, p)
    return paths


def which(cmd: str):
    names = [cmd]
    if IS_WINDOWS and not cmd.endswith(".exe"):
        names.append(cmd + ".exe")
    for p in brew_aware_path():
        for name in names:
            candidate = Path(p) / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
    return shutil.which(cmd)


def check_python_packages() -> dict:
    if IS_BUNDLED:
        # Inside a PyInstaller bundle every dep is already packaged in
        return {"venv_ready": True, "missing": [], "present": list(CORE_IMPORTS.keys())}
    if not VENV_PY.exists():
        return {"venv_ready": False, "missing": list(CORE_IMPORTS.keys()), "present": []}
    mapping = list(CORE_IMPORTS.items())
    script = (
        "import json, importlib.util\n"
        f"mapping = {json.dumps(mapping)}\n"
        "present, missing = [], []\n"
        "for pip_name, import_name in mapping:\n"
        "    spec = None\n"
        "    try:\n"
        "        spec = importlib.util.find_spec(import_name)\n"
        "    except Exception:\n"
        "        spec = None\n"
        "    (present if spec is not None else missing).append(pip_name)\n"
        "print(json.dumps({'present': present, 'missing': missing}))\n"
    )
    try:
        r = subprocess.run(
            arch_pinned_cmd([VENV_PY, "-c", script]),
            capture_output=True, text=True, timeout=30,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if r.returncode != 0:
            return {"venv_ready": True, "missing": list(CORE_IMPORTS.keys()), "present": []}
        data = json.loads(r.stdout.strip().splitlines()[-1])
        return {"venv_ready": True, "missing": data["missing"], "present": data["present"]}
    except Exception:
        return {"venv_ready": True, "missing": list(CORE_IMPORTS.keys()), "present": []}


def check_whisper_model(name: str = "small") -> bool:
    cache = Path.home() / ".cache" / "whisper"
    if not cache.exists():
        return False
    return any(p.name.startswith(name) and p.suffix == ".pt" for p in cache.iterdir())


class Api:
    def __init__(self):
        self.server_proc: subprocess.Popen | None = None
        self._server_thread: threading.Thread | None = None
        self._uvicorn_server = None

    def _push_log(self, line: str) -> None:
        if not webview.windows:
            return
        try:
            webview.windows[0].evaluate_js(
                f"window.pushSetupLog && window.pushSetupLog({json.dumps(line)})"
            )
        except Exception:
            pass

    def _stream_cmd(self, cmd: list, timeout: int = 1800) -> int:
        self._push_log("$ " + " ".join(str(c) for c in cmd))
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=_SUBPROCESS_FLAGS,
            )
        except Exception as e:
            self._push_log(f"[error launching: {e}]")
            return -1
        start = time.time()
        assert proc.stdout is not None
        while True:
            if proc.poll() is not None and not proc.stdout.readable():
                break
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            if time.time() - start > timeout:
                proc.kill()
                self._push_log("[timed out]")
                return -1
            self._push_log(line.rstrip())
        proc.wait()
        return proc.returncode

    def check_all(self) -> dict:
        return {
            "platform": "windows" if IS_WINDOWS else ("mac" if IS_MAC else "linux"),
            "bundled": IS_BUNDLED,
            "brew": which("brew") is not None,
            "winget": which("winget") is not None if IS_WINDOWS else False,
            "ffmpeg": which("ffmpeg") is not None,
            "ffprobe": which("ffprobe") is not None,
            "python3": which("python3") is not None or which("python") is not None or Path("/usr/bin/python3").exists(),
            "packages": check_python_packages(),
            "whisper_small": check_whisper_model("small"),
        }

    def open_brew_install_in_terminal(self) -> dict:
        if not IS_MAC:
            return {"ok": False, "error": "Homebrew is Mac-only."}
        cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "Terminal" to do script "{cmd}"',
                 "-e", 'tell application "Terminal" to activate'],
                check=True,
            )
            return {"ok": True, "message": "Follow the prompts in the Terminal window. When it finishes, come back and click Re-check."}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": str(e)}

    def install_ffmpeg(self) -> dict:
        if IS_WINDOWS:
            winget = which("winget")
            if not winget:
                return {"ok": False, "error": "winget not found. Update Windows or install from the Microsoft Store, then try again."}
            self._push_log("Installing media tools via winget — a Windows permission prompt may appear.")
            rc = self._stream_cmd(
                [winget, "install", "--silent", "--accept-source-agreements", "--accept-package-agreements", "-e", "--id", "Gyan.FFmpeg"],
                timeout=900,
            )
            return {"ok": rc == 0}
        brew = which("brew")
        if not brew:
            return {"ok": False, "error": "Install the package manager first."}
        rc = self._stream_cmd([brew, "install", "ffmpeg"], timeout=900)
        return {"ok": rc == 0}

    def install_packages(self) -> dict:
        if IS_BUNDLED:
            return {"ok": True}  # everything already bundled
        if not VENV_PY.exists():
            py = which("python3") or which("python") or ("/usr/bin/python3" if not IS_WINDOWS else None)
            if not py:
                return {"ok": False, "error": "Python 3 is not installed."}
            self._push_log("Preparing the app environment…")
            rc = self._stream_cmd([py, "-m", "venv", str(ROOT / "venv")], timeout=180)
            if rc != 0:
                return {"ok": False, "error": "Could not create venv"}
        self._push_log("Upgrading pip…")
        self._stream_cmd(arch_pinned_cmd([VENV_PY, "-m", "pip", "install", "--upgrade", "pip"]), timeout=300)
        self._push_log("Installing app components — this can take several minutes on first run.")
        rc = self._stream_cmd(
            arch_pinned_cmd([VENV_PY, "-m", "pip", "install", "-r", REQS]),
            timeout=1800,
        )
        if rc != 0:
            return {"ok": False, "error": f"pip install exited with code {rc}"}
        check = check_python_packages()
        if check["missing"]:
            return {"ok": False, "error": "Still missing: " + ", ".join(check["missing"])}
        return {"ok": True}

    def download_whisper_model(self, name: str = "small") -> dict:
        self._push_log("Downloading the transcription model (one-time, ~460 MB)…")
        if IS_BUNDLED:
            try:
                import whisper  # type: ignore
                whisper.load_model(name)
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        if not VENV_PY.exists():
            return {"ok": False, "error": "Install app components first."}
        code = (
            "import whisper, sys\n"
            f"whisper.load_model({name!r})\n"
            "print('whisper_model_ready')\n"
        )
        rc = self._stream_cmd(arch_pinned_cmd([VENV_PY, "-c", code]), timeout=1800)
        return {"ok": rc == 0}

    def launch_app(self) -> dict:
        if self._uvicorn_server is not None or (self.server_proc and self.server_proc.poll() is None):
            if webview.windows:
                webview.windows[0].load_url(SERVER_URL)
            return {"ok": True}

        if IS_BUNDLED:
            # Run uvicorn in-process; no separate Python interpreter exists inside the .exe
            try:
                import uvicorn
                import app as fastapi_app
            except Exception as e:
                return {"ok": False, "error": f"Could not import server: {e}"}
            config = uvicorn.Config(fastapi_app.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="off")
            self._uvicorn_server = uvicorn.Server(config)

            def _run():
                import asyncio
                asyncio.run(self._uvicorn_server.serve())

            self._server_thread = threading.Thread(target=_run, daemon=True)
            self._server_thread.start()
        else:
            try:
                self.server_proc = subprocess.Popen(
                    arch_pinned_cmd([VENV_PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(PORT)]),
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=_SUBPROCESS_FLAGS,
                )
            except Exception as e:
                return {"ok": False, "error": f"Could not start server: {e}"}

        server_log_path = ROOT / ".server.log"
        server_log_path.write_text("")
        captured: list[str] = []

        def _drain():
            proc = self.server_proc
            if not proc or not proc.stdout:
                return
            try:
                with open(server_log_path, "a") as f:
                    for line in proc.stdout:
                        captured.append(line)
                        f.write(line)
                        f.flush()
            except Exception:
                pass

        drain_thread = threading.Thread(target=_drain, daemon=True)
        drain_thread.start()

        for _ in range(120):
            if not IS_BUNDLED and self.server_proc and self.server_proc.poll() is not None:
                time.sleep(0.1)  # let drain catch up
                out = "".join(captured)
                tail = out.strip().splitlines()[-5:] if out.strip() else []
                detail = " | ".join(tail) if tail else "no output captured"
                self._push_log(out.strip() or "(server produced no output)")
                return {"ok": False, "error": f"Server exited (code {self.server_proc.returncode}): {detail}"}
            try:
                with urlopen(SERVER_URL + "/api/auth/status", timeout=1) as r:
                    if r.status == 200:
                        break
            except URLError:
                time.sleep(0.25)
        else:
            return {"ok": False, "error": "Server did not come up on port 8765"}

        if webview.windows:
            webview.windows[0].load_url(SERVER_URL)
        return {"ok": True}


def _shutdown(api: Api):
    if api._uvicorn_server is not None:
        try:
            api._uvicorn_server.should_exit = True
        except Exception:
            pass
    if api.server_proc and api.server_proc.poll() is None:
        try:
            api.server_proc.terminate()
            api.server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            api.server_proc.kill()


def main():
    api = Api()
    window = webview.create_window(
        "Feedscript",
        str(SETUP_HTML),
        js_api=api,
        width=1100,
        height=780,
        min_size=(900, 600),
    )

    def on_closed():
        _shutdown(api)

    window.events.closed += on_closed

    def _sig(*_):
        _shutdown(api)
        sys.exit(0)
    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

    webview.start()
    _shutdown(api)


if __name__ == "__main__":
    main()
