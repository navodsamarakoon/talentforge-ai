import io
import json
import subprocess
from urllib.error import URLError

import pytest

from talentforge.sandbox import CaseResult, DockerSandbox, RemoteSandbox, SandboxUnavailable


class HangingDockerProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_docker_run_uses_isolation_flags_and_reports_timeout(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def popen(command, **kwargs):
        commands.append(command)
        process = HangingDockerProcess(command, **kwargs)
        process.stdout = io.BytesIO(b"__TALENTFORGE_STARTED__\n")
        return process

    monkeypatch.setattr("talentforge.sandbox.subprocess.run", run)
    monkeypatch.setattr("talentforge.sandbox.subprocess.Popen", popen)
    sandbox = DockerSandbox()
    sandbox.timeout = 0.05

    results = sandbox.run("def solve(): return 1", "solve", [{"input_args": [], "expected_output": 1}])

    assert [item.status for item in results] == ["timeout"]
    assert commands[0][0:2] == ["docker", "version"]
    assert commands[1][0:3] == ["docker", "image", "inspect"]
    docker_command = commands[2]
    assert "-i" in docker_command
    assert "--pull=never" in docker_command
    assert "--network=none" in docker_command
    assert "--read-only" in docker_command
    assert "--cap-drop=ALL" in docker_command
    assert "--security-opt=no-new-privileges" in docker_command
    assert "--user=65534:65534" in docker_command
    assert "--pids-limit=32" in docker_command
    assert "--memory=128m" in docker_command
    assert "--cpus=0.5" in docker_command
    assert "--tmpfs=/tmp:rw,noexec,nosuid,size=8m" in docker_command
    assert "--ulimit=fsize=1048576:1048576" in docker_command
    assert "--mount" not in docker_command
    assert any(command[:3] == ["docker", "rm", "-f"] for command in commands)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(FileNotFoundError("docker"), id="docker-cli-missing"),
        pytest.param(PermissionError("permission denied accessing /var/run/docker.sock"), id="socket-permission-denied"),
    ],
)
def test_docker_unavailable_fails_closed_without_host_execution(monkeypatch, error):
    popen_calls = []

    def run(command, **kwargs):
        raise error

    def popen(command, **kwargs):
        popen_calls.append(command)
        raise AssertionError("candidate code must not execute without Docker")

    monkeypatch.setattr("talentforge.sandbox.subprocess.run", run)
    monkeypatch.setattr("talentforge.sandbox.subprocess.Popen", popen)
    with pytest.raises(SandboxUnavailable, match="Docker CLI, daemon, or sandbox image is unavailable"):
        DockerSandbox().run("raise RuntimeError('must not run on host')", "solve", [])
    assert popen_calls == []


def test_successful_sandbox_execution_uses_isolated_container(monkeypatch):
    commands = []
    result = b"__TALENTFORGE_STARTED__\n" + json.dumps({
        "results": [{"status": "ok", "value": 1, "duration_ms": 2}],
    }).encode("utf-8")

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    def popen(command, **kwargs):
        commands.append(command)
        process = HangingDockerProcess(command, **kwargs)
        process.stdout = io.BytesIO(result)
        process.returncode = 0
        return process

    monkeypatch.setattr("talentforge.sandbox.subprocess.run", run)
    monkeypatch.setattr("talentforge.sandbox.subprocess.Popen", popen)

    results = DockerSandbox().run(
        "def solve(): return 1",
        "solve",
        [{"input_args": [], "expected_output": 1}],
    )

    assert [(item.passed, item.status, item.duration_ms) for item in results] == [(True, "passed", 2)]
    docker_command = commands[2]
    assert "-i" in docker_command
    assert "--network=none" in docker_command
    assert "--read-only" in docker_command
    assert "--cap-drop=ALL" in docker_command
    assert "--security-opt=no-new-privileges" in docker_command
    assert "--memory=128m" in docker_command
    assert "--cpus=0.5" in docker_command
    assert "--pids-limit=32" in docker_command


def test_remote_sandbox_forwards_cases_and_returns_results(monkeypatch):
    request_data = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def urlopen(request, timeout):
        request_data.append((request, timeout))
        return Response(json.dumps([{
            "passed": True,
            "status": "passed",
            "message": "",
            "duration_ms": 3,
        }]).encode("utf-8"))

    monkeypatch.setattr("talentforge.sandbox.urlopen", urlopen)
    cases = [{"input_args": [2], "expected_output": 2}]

    results = RemoteSandbox("http://sandbox-runner:8001/").run("def solve(n): return n", "solve", cases)

    request, timeout = request_data[0]
    assert request.full_url == "http://sandbox-runner:8001/run"
    assert timeout == 300
    assert json.loads(request.data) == {
        "code": "def solve(n): return n",
        "function_name": "solve",
        "cases": cases,
    }
    assert results == [CaseResult(True, "passed", "", 3)]


def test_remote_sandbox_connection_failure_fails_closed(monkeypatch):
    def urlopen(_request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("talentforge.sandbox.urlopen", urlopen)

    with pytest.raises(SandboxUnavailable, match="Sandbox runner is unavailable"):
        RemoteSandbox("http://sandbox-runner:8001").run("def solve(): pass", "solve", [])
