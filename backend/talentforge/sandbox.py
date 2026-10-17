import json
import subprocess
import threading
import time
from uuid import uuid4
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from talentforge.config import get_settings


@dataclass
class CaseResult:
    passed: bool
    status: str
    message: str = ""
    duration_ms: int | None = None


class Sandbox(Protocol):
    def run(self, code: str, function_name: str, cases: list[dict[str, object]]) -> list[CaseResult]: ...


class SandboxUnavailable(RuntimeError):
    pass


class RemoteSandbox:
    def __init__(self, runner_url: str | None = None):
        self.runner_url = (runner_url or get_settings().sandbox_runner_url).rstrip("/")

    def run(self, code: str, function_name: str, cases: list[dict[str, object]]) -> list[CaseResult]:
        request = Request(
            f"{self.runner_url}/run",
            data=json.dumps({
                "code": code,
                "function_name": function_name,
                "cases": cases,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=300) as response:
                response_body = response.read(1_000_001)
            if len(response_body) > 1_000_000:
                raise ValueError("Sandbox runner response exceeded its size limit.")
            rows = json.loads(response_body.decode("utf-8", errors="strict"))
            if not isinstance(rows, list) or len(rows) != len(cases):
                raise ValueError("Sandbox runner returned the wrong result count.")
            if any(
                not isinstance(row, dict)
                or not isinstance(row.get("passed"), bool)
                or not isinstance(row.get("status"), str)
                or not isinstance(row.get("message", ""), str)
                or (row.get("duration_ms") is not None and not isinstance(row.get("duration_ms"), int))
                for row in rows
            ):
                raise ValueError("Sandbox runner returned malformed results.")
        except (OSError, TimeoutError, URLError) as error:
            raise SandboxUnavailable("Sandbox runner is unavailable.") from error
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise SandboxUnavailable("Sandbox runner returned an invalid response.") from error

        return [
            CaseResult(
                passed=row["passed"],
                status=row["status"],
                message=row.get("message", ""),
                duration_ms=row.get("duration_ms"),
            )
            for row in rows
        ]


class DockerSandbox:
    def __init__(self, image: str | None = None):
        self.image = image or get_settings().sandbox_image
        self.timeout = get_settings().sandbox_timeout_seconds

    def run(self, code: str, function_name: str, cases: list[dict[str, object]]) -> list[CaseResult]:
        if len(code) > get_settings().sandbox_max_code_chars:
            return [CaseResult(False, "input_limit", "Submitted code exceeds the configured size limit.") for _ in cases]
        try:
            subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], check=True, capture_output=True, timeout=3)
            image = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if image.returncode != 0:
                subprocess.run(["docker", "pull", self.image], check=True, capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as error:
            raise SandboxUnavailable("Docker CLI, daemon, or sandbox image is unavailable.") from error

        runner = r'''import contextlib, io, json, sys, time
payload = json.loads(sys.stdin.read())
namespace = {"__name__": "__candidate__"}
print("__TALENTFORGE_STARTED__", flush=True)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    exec(compile(payload["code"], "<candidate>", "exec"), namespace)
function = namespace.get(payload["function_name"])
if not callable(function):
    print(json.dumps({"error": "Expected function is missing."}))
    raise SystemExit(0)
results = []
for args in payload["cases"]:
    started = time.monotonic()
    try:
        value = function(*args)
        encoded = json.dumps(value, separators=(",", ":"))
        if len(encoded) > 65536:
            results.append({"status": "output_limit", "message": "Returned value exceeded the output limit."})
            continue
        results.append({"status": "ok", "value": value, "duration_ms": int((time.monotonic()-started)*1000)})
    except BaseException as error:
        results.append({"status": "runtime_error", "message": type(error).__name__ + ": " + str(error)[:300]})
encoded = json.dumps({"results": results}, separators=(",", ":"))
if len(encoded) > 65536:
    print(json.dumps({"error": "Sandbox output exceeded its limit."}))
else:
    print(encoded)
'''
        container_name = f"talentforge-run-{uuid4().hex[:16]}"
        command = [
            "docker", "run", "-i", "--rm", "--pull=never", "--name", container_name, "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=32", "--memory=128m", "--cpus=0.5",
            "--ulimit=nofile=64:64", "--ulimit=fsize=1048576:1048576", "--ulimit=core=0:0",
            "--user=65534:65534", "--tmpfs=/tmp:rw,noexec,nosuid,size=8m",
            "--entrypoint", "python", self.image, "-c", runner,
        ]
        input_payload = json.dumps({
            "code": code,
            "function_name": function_name,
            "cases": [case["input_args"] for case in cases],
        }).encode("utf-8")
        process: subprocess.Popen[bytes] | None = None
        output = bytearray()
        errors = bytearray()
        overflow = threading.Event()
        execution_started = threading.Event()
        start_marker = b"__TALENTFORGE_STARTED__\n"
        startup_timeout = 30

        def drain(stream: BinaryIO, destination: bytearray) -> None:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                if len(destination) < 65536:
                    destination.extend(chunk[:65536 - len(destination)])
                if len(chunk) + len(destination) > 65536:
                    overflow.set()
                if destination is output and start_marker in destination:
                    execution_started.set()

        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            output_reader = threading.Thread(target=drain, args=(process.stdout, output), daemon=True)
            error_reader = threading.Thread(target=drain, args=(process.stderr, errors), daemon=True)
            output_reader.start()
            error_reader.start()
            try:
                process.stdin.write(input_payload)
                process.stdin.close()
            except OSError:
                pass
            started = time.monotonic()
            execution_started_at: float | None = None
            timed_out = False
            while process.poll() is None:
                if overflow.is_set():
                    process.terminate()
                    break
                now = time.monotonic()
                if execution_started.is_set():
                    if execution_started_at is None:
                        execution_started_at = now
                elif now - started > startup_timeout:
                    timed_out = True
                    process.terminate()
                    break
                if execution_started_at is not None and now - execution_started_at > self.timeout:
                    timed_out = True
                    process.terminate()
                    break
                time.sleep(0.025)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            output_reader.join(timeout=1)
            error_reader.join(timeout=1)
        except OSError as error:
            raise SandboxUnavailable("Docker CLI could not be started.") from error
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            try:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=3, check=False)
            except (OSError, subprocess.SubprocessError):
                pass

        if overflow.is_set():
            return [CaseResult(False, "output_limit", "Sandbox output exceeded its limit.") for _ in cases]
        if process is None:
            raise SandboxUnavailable("Sandbox process could not be started.")
        if timed_out:
            return [CaseResult(False, "timeout", "Execution exceeded the time limit.") for _ in cases]
        if process.returncode != 0:
            message = errors.decode("utf-8", errors="replace")[:1_000]
            status = "resource_limit" if "memory" in message.lower() or "killed" in message.lower() else "runtime_error"
            return [CaseResult(False, status, message or "Sandbox execution failed.") for _ in cases]
        try:
            output_bytes = bytes(output)
            if output_bytes.startswith(start_marker):
                output_bytes = output_bytes[len(start_marker):]
            output_value = json.loads(output_bytes.decode("utf-8", errors="strict"))
            if not isinstance(output_value, dict):
                raise ValueError("Sandbox output must be a JSON object.")
            if "error" in output_value:
                return [CaseResult(False, "runtime_error", str(output_value["error"])) for _ in cases]
            rows = output_value["results"]
            if not isinstance(rows, list) or len(rows) != len(cases):
                raise ValueError("Sandbox returned the wrong result count.")
            if any(not isinstance(row, dict) or row.get("status") not in {"ok", "runtime_error", "output_limit"}
                   for row in rows):
                raise ValueError("Sandbox returned a malformed test result.")
            if any(row.get("status") == "ok" and "value" not in row for row in rows):
                raise ValueError("Sandbox omitted a returned test value.")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            return [CaseResult(False, "invalid_output", f"Sandbox returned invalid output: {error}") for _ in cases]

        return [
            CaseResult(
                passed=row.get("status") == "ok" and row.get("value") == case["expected_output"],
                status="passed" if row.get("status") == "ok" and row.get("value") == case["expected_output"]
                else str(row.get("status", "invalid_output")),
                message="" if row.get("status") == "ok" else str(row.get("message", "Execution failed."))[:500],
                duration_ms=row.get("duration_ms") if isinstance(row.get("duration_ms"), int) else None,
            )
            for row, case in zip(rows, cases, strict=True)
        ]
