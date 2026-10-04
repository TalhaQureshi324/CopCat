"""Sandbox parent: launches `copcat.sandbox_worker` in an isolated child
process and enforces resource limits.

Security model (why this is not a plain subprocess.run of student code):
* student code NEVER runs in the grader process — it loads in a throwaway
  interpreter whose only channel back is one JSON document
* Windows: the child is assigned to a **Job Object** (ctypes, stdlib) with
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (fork-bomb / orphan containment) and
  JOB_OBJECT_LIMIT_PROCESS_MEMORY (memory-cap); CREATE_NO_WINDOW hides it
* POSIX: preexec_fn applies resource.setrlimit (CPU seconds + address space)
* hard timeout with process kill on expiry
"""

import json
import os
import subprocess
import sys
import tempfile


def _posix_preexec(memory_mb, cpu_s):
    def apply():
        import resource
        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s + 5, cpu_s + 5))
    return apply


class _WinJob:
    """ctypes Job Object: memory cap + kill-on-close (no pywin32 needed)."""

    def __init__(self, memory_mb):
        import ctypes
        self.ctypes = ctypes
        self.k32 = ctypes.windll.kernel32
        self.handle = self.k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObjectW failed")

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]

        class EXT_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXT_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x100  # KILL_ON_CLOSE | PROCESS_MEMORY
        info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        if not self.k32.SetInformationJobObject(
                self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject failed")

    def assign(self, proc):
        self.k32.AssignProcessToJobObject(self.handle, int(proc._handle))

    def close(self):
        if getattr(self, "handle", None):
            self.k32.TerminateJobObject(self.handle, 0)
            self.k32.CloseHandle(self.handle)
            self.handle = None


def run_sandboxed(path, probes, timeout_s=15.0, memory_mb=512, aliases=None,
                  mock_inputs=None):
    """Import `path` in the sandbox and run functional probes.

    probes: [{id, construct, call?, set_expr?}]
    aliases: {required_name: student_name} - structural interface bindings
    mock_inputs: list of strings returned by input() in order (then "")
    Returns {crash, stdout_tail, duration_ms, probes:{id:{status,...}}}
    """
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "sandbox_worker.py")
    spec = {"path": os.path.abspath(path), "probes": probes,
            "workdir": os.path.abspath(path),
            "aliases": aliases or {},
            "mock_inputs": mock_inputs or []}
    job = None
    preexec = None
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            job = _WinJob(memory_mb)
        except OSError:
            job = None        # degrade to timeout-only containment
    else:
        preexec = _posix_preexec(memory_mb, int(timeout_s) + 5)

    try:
        proc = subprocess.Popen(
            [sys.executable, worker],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, cwd=tempfile.gettempdir(),
            creationflags=creationflags, preexec_fn=preexec)
        if job is not None:
            job.assign(proc)
        try:
            out, _ = proc.communicate(json.dumps(spec), timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return {"crash": "sandbox timeout after {}s".format(timeout_s),
                    "stdout_tail": "", "duration_ms": int(timeout_s * 1000),
                    "probes": {}}
        if not out.strip():
            return {"crash": "sandbox worker produced no output (exit code {})"
                    .format(proc.returncode),
                    "stdout_tail": "", "duration_ms": 0, "probes": {}}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"crash": "sandbox worker output was not valid JSON",
                    "stdout_tail": out[-4000:], "duration_ms": 0, "probes": {}}
    finally:
        if job is not None:
            job.close()
