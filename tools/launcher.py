"""DataPilot one-click launcher.

Compiled to DataPilot.exe with tools/build-exe.bat. Double-clicking it should
take someone from a fresh clone to a working app with no other steps: it
installs whatever is missing, starts both servers, waits for them, and opens
the browser. Closing the window stops everything.

The exe is a *launcher*, not a bundle of the whole stack — Python and Node
still have to be on the machine. Bundling a Python interpreter, a Node runtime
and node_modules would be a several-hundred-megabyte artifact, and the point
here is to remove setup friction for a judge, not to ship an installer.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_URL = "http://localhost:8080"
API_URL = "http://127.0.0.1:8000"
STARTUP_TIMEOUT = 180  # first run installs packages, so allow plenty

IS_WINDOWS = os.name == "nt"
processes: list[subprocess.Popen] = []

# Kept alive for the life of the process: if this handle is closed, Windows
# kills the whole job — which is exactly what we want to happen only on exit.
_job_handle = None


def bind_children_to_this_process() -> None:
    """Make the servers die with the launcher, even on a hard kill.

    Graceful shutdown covers Ctrl+C, but closing the console window or ending
    the task from Task Manager kills us outright, and the API and web server
    would otherwise keep holding ports 8000 and 8080 with no window to stop
    them from.

    On Windows the OS-level guarantee is a Job Object with
    KILL_ON_JOB_CLOSE — children inherit the job, and the job dies with us.
    On POSIX the launcher becomes a process-group leader and the group is
    signalled on exit.
    """
    global _job_handle
    if not IS_WINDOWS:
        try:
            os.setpgrp()
        except (AttributeError, OSError):
            pass
        return

    import ctypes
    from ctypes import wintypes

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # HANDLE returns and arguments must be declared explicitly. Left to
        # ctypes' default of int, a 64-bit handle is truncated and every call
        # fails with ERROR_INVALID_HANDLE.
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            return
        if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
            return
        _job_handle = job
    except Exception:  # noqa: BLE001
        # Not fatal — graceful shutdown still works, we just lose the
        # guarantee for hard kills.
        pass


# --------------------------------------------------------------------------
# console helpers
# --------------------------------------------------------------------------

def say(message: str = "") -> None:
    print(f"  {message}" if message else "")
    sys.stdout.flush()


def fail(message: str, hint: str = "") -> None:
    say()
    say(f"[X] {message}")
    if hint:
        for line in hint.splitlines():
            say(f"    {line}")
    say()
    if IS_WINDOWS:
        os.system("pause")
    sys.exit(1)


def project_root() -> Path:
    """Where the app lives.

    Frozen: next to the exe (and one level up, so the exe can also sit in a
    tools/ or dist/ folder). Unfrozen: the repo root above this file.
    """
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
        for candidate in (here, here.parent):
            if (candidate / "backend" / "requirements.txt").is_file():
                return candidate
        return here
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# prerequisites
# --------------------------------------------------------------------------

def find_python() -> str:
    """A real interpreter — sys.executable is the exe itself when frozen."""
    for name in ("python", "python3", "py"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            out = subprocess.run(
                [path, "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True, text=True, timeout=20,
            )
            if out.returncode == 0 and "(3," in out.stdout:
                minor = int(out.stdout.split(",")[1].strip().rstrip(")"))
                if minor >= 10:
                    return path
        except Exception:
            continue
    fail(
        "Python 3.10+ was not found.",
        "Install it from https://python.org and tick\n"
        '"Add python.exe to PATH" during setup, then run this again.',
    )
    return ""  # unreachable


def find_node_package_manager() -> str:
    for name in ("bun", "npm"):
        if shutil.which(name):
            return name
    fail(
        "Neither Bun nor Node.js was found.",
        "Install Node.js LTS from https://nodejs.org, then run this again.",
    )
    return ""  # unreachable


def venv_python(root: Path) -> Path:
    venv = root / "backend" / ".venv"
    return venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------

def ensure_backend(root: Path, system_python: str) -> Path:
    py = venv_python(root)
    if py.is_file():
        say("[1/4] Python environment ready.")
        return py

    say("[1/4] Creating the Python environment (first run only, ~1 min)...")
    result = subprocess.run(
        [system_python, "-m", "venv", str(root / "backend" / ".venv")],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not py.is_file():
        fail("Could not create the virtual environment.", result.stderr.strip()[:500])

    say("      Installing backend packages...")
    result = subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-r", str(root / "backend" / "requirements.txt")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        fail("Backend packages failed to install.", result.stderr.strip()[-800:])
    return py


def ensure_frontend(root: Path, pkg: str) -> None:
    if (root / "frontend" / "node_modules").is_dir():
        say("[2/4] Frontend packages ready.")
        return
    say(f"[2/4] Installing frontend packages with {pkg} (first run only, ~2 min)...")
    result = subprocess.run(
        [pkg, "install"], cwd=root / "frontend",
        shell=IS_WINDOWS, capture_output=True, text=True,
    )
    if result.returncode != 0:
        fail("Frontend packages failed to install.", result.stderr.strip()[-800:])


def ensure_env(root: Path) -> None:
    env, example = root / "backend" / ".env", root / "backend" / ".env.example"
    if not env.is_file() and example.is_file():
        shutil.copyfile(example, env)
        say("      Created backend/.env - add an API key there for full AI mode.")
        say("      Without one the app still runs on its offline engine.")


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def pids_on_port(port: int) -> list[int]:
    """PIDs listening on a TCP port, best effort."""
    try:
        if IS_WINDOWS:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=15,
            ).stdout
            pids = set()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
                    pids.add(int(parts[4]))
            return sorted(pids)
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        return [int(x) for x in out.split()]
    except Exception:  # noqa: BLE001
        return []


def is_our_api(port: int) -> bool:
    """True when whatever holds the port is a DataPilot API we can reclaim."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return "DataPilot" in r.read(400).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False


def free_ports_or_explain(ports: tuple[int, ...] = (8000, 8080)) -> None:
    """Reclaim ports left by a previous run; refuse to touch anything else.

    A launcher that silently fails to bind is the most likely way a first
    double-click goes wrong, so this is handled before either server starts —
    and an unrelated program on port 8000 is reported rather than killed.
    """
    ours = is_our_api(8000)
    for port in ports:
        pids = pids_on_port(port)
        if not pids:
            continue
        if not ours:
            fail(
                f"Port {port} is already in use by another program (PID {pids[0]}).",
                "DataPilot needs ports 8000 and 8080.\n"
                "Close that program, or stop the process, and run this again.",
            )
        say(f"      Reclaiming port {port} from a previous DataPilot run...")
        for pid in pids:
            try:
                if IS_WINDOWS:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, timeout=15)
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass
    # Give the OS a moment to release the sockets.
    for _ in range(10):
        if not any(pids_on_port(p) for p in ports):
            return
        time.sleep(0.5)


def spawn(command: list[str], cwd: Path, label: str) -> subprocess.Popen:
    """Start a server, echoing only its errors so the console stays readable."""
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    proc = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, shell=IS_WINDOWS and command[0] in ("bun", "npm"),
        creationflags=creationflags,
    )
    processes.append(proc)

    def pump() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.rstrip()
            if text and not text.startswith(("INFO:", "WARNING:  StatReload")):
                say(f"  [{label}] {text}")

    threading.Thread(target=pump, daemon=True).start()
    return proc


def wait_for(url: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for proc in processes:
            if proc.poll() is not None:
                return False  # a server died; stop waiting
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def shutdown(*_args) -> None:
    say()
    say("Stopping DataPilot...")
    for proc in processes:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in processes:
        try:
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    # `npm run dev` on Windows is a cmd.exe wrapper, so terminating it can
    # leave the real node process holding port 8080. The job object catches
    # that on exit; on POSIX, signal the whole group for the same reason.
    if not IS_WINDOWS:
        try:
            os.killpg(os.getpgrp(), signal.SIGTERM)
        except (AttributeError, OSError, ProcessLookupError):
            pass


def main() -> None:
    root = project_root()
    if not (root / "backend" / "requirements.txt").is_file():
        fail(
            "Could not find the DataPilot project files.",
            f"Looked in: {root}\n"
            "Keep this launcher in the project folder, next to the\n"
            "'backend' and 'frontend' directories.",
        )

    print()
    say("DataPilot AI")
    say("============")
    print()

    if len(sys.argv) > 1 and sys.argv[1].lower() == "reset":
        say("Resetting demo data...")
        for pattern in ("backend/data/*.db", "backend/db/*.db"):
            for path in root.glob(pattern):
                try:
                    path.unlink()
                except OSError:
                    pass
        say("Done - the database will be re-seeded on the next start.")
        print()

    system_python = find_python()
    pkg = find_node_package_manager()

    py = ensure_backend(root, system_python)
    ensure_frontend(root, pkg)
    ensure_env(root)

    # Do this before spawning anything, so the servers are born inside the job.
    bind_children_to_this_process()
    signal.signal(signal.SIGINT, shutdown)
    free_ports_or_explain()

    say("[3/4] Starting the API on http://localhost:8000 ...")
    spawn([str(py), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
          root / "backend", "api")

    say("[4/4] Starting the web app on http://localhost:8080 ...")
    spawn([pkg, "run", "dev"], root / "frontend", "web")

    print()
    say("Waiting for the app to come up...")

    if not wait_for(f"{API_URL}/health", 90):
        shutdown()
        fail("The API did not start.", "Scroll up for the error it reported.")

    if wait_for(APP_URL, STARTUP_TIMEOUT):
        webbrowser.open(APP_URL)
        say("Ready - DataPilot is open in your browser.")
    else:
        say("The web app is taking longer than usual.")
        say(f"Try opening {APP_URL} yourself in a moment.")

    print()
    say(f"App    {APP_URL}")
    say(f"API    {API_URL}")
    say(f"Docs   {API_URL}/docs")
    print()
    say("Keep this window open. Press Ctrl+C, or close it, to stop DataPilot.")
    print()

    try:
        while True:
            time.sleep(1)
            dead = [p for p in processes if p.poll() is not None]
            if dead:
                say("A server stopped unexpectedly. Shutting down.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        shutdown()
        fail(f"Unexpected error: {exc}")
