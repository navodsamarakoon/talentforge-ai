from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from talentforge.sandbox import DockerSandbox, SandboxUnavailable


class SandboxCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_args: list[Any]
    expected_output: Any


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=100_000)
    function_name: str = Field(min_length=1, max_length=200)
    cases: list[SandboxCase] = Field(max_length=200)


app = FastAPI()


@app.exception_handler(SandboxUnavailable)
async def sandbox_unavailable_handler(_request: Request, error: SandboxUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.post("/run")
def run_sandbox(request: SandboxRequest) -> list[dict[str, object]]:
    results = DockerSandbox().run(
        request.code,
        request.function_name,
        [case.model_dump() for case in request.cases],
    )
    return [asdict(result) for result in results]
