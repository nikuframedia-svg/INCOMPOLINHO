"""Copilot FastAPI endpoint — Spec 10.

POST /api/copilot/chat  — LLM chat with function calling
POST /api/copilot/load  — Deprecated; use the two-stage data upload API
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.api.console import router as console_router
from backend.api.data import router as data_router
from backend.api.manual_plan import router as manual_plan_router
from backend.api.plans import router as plans_router
from backend.api.replan import router as replan_router
from backend.api.robustness import router as robustness_router
from backend.api.scenarios import router as scenarios_router
from backend.config.loader import DEFAULT_CONFIG_PATH, load_config
from backend.copilot.engine import execute_tool
from backend.copilot.llm_provider import get_provider
from backend.copilot.prompts import build_system_prompt
from backend.copilot.state import state
from backend.copilot.tools import TOOLS
from backend.planning_control import PlanningCancelled, PlanningTimeout

logger = logging.getLogger(__name__)

load_dotenv()


def _cors_origins() -> list[str]:
    configured = os.getenv("PP1_CORS_ORIGINS", "")
    if configured.strip():
        return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Restore the most recent persistent plan on process startup."""
    from backend.plans.transactions import recover_pending_mutations

    recover_pending_mutations(state.get_plans_store())
    if state.engine_data is None:
        try:
            from backend.plans.restore import restore_plan_into_state

            latest = state.get_plans_store().active()
            if latest is not None:
                config = load_config(DEFAULT_CONFIG_PATH)
                state.config = config
                state.default_config = copy.deepcopy(config)
                restore_plan_into_state(
                    latest,
                    state,
                    autosave=False,
                    approve_exceptions=True,
                    approval_reason="Reposição automática do último plano guardado",
                    approval_author="sistema",
                    recover_jit_blocked=False,
                    prefer_current_config=True,
                    preserve_exact=True,
                    recover_existing=True,
                )
                logger.info("Restored plan %s on startup", latest["id"])
        except Exception:
            logger.exception("Could not restore the explicit active plan; startup refused")
            raise
    state._load_rules()
    # Jobs interrupted by a restart are not resumed; refresh a missing or stale
    # analysis of the restored revision. Information only: never blocks startup.
    try:
        from backend.risk.jobs import enqueue_after_commit

        enqueue_after_commit(state)
    except Exception:
        logger.exception("Automatic robustness job not started on startup")
    from backend.loading.jobs import LoadJobManager

    load_logger = logging.getLogger("backend.loading")
    if not load_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        load_logger.addHandler(handler)
        load_logger.setLevel(logging.INFO)
        load_logger.propagate = False
    manager = getattr(_app.state, "load_jobs", None)
    if manager is None or manager.closed:
        manager = LoadJobManager(state)
        _app.state.load_jobs = manager
    try:
        yield
    finally:
        await manager.close()


app = FastAPI(title="PP1 Copilot", version="1.0.0", lifespan=lifespan)


@app.exception_handler(PlanningTimeout)
async def planning_timeout_handler(_request: Request, _exc: PlanningTimeout):
    """Expose an explicit timeout without publishing a partial candidate."""
    return JSONResponse(
        status_code=504,
        content={
            "detail": {
                "code": "planning_timeout",
                "message": "O calculo excedeu o tempo limite; o plano ativo nao foi alterado.",
            }
        },
    )


@app.exception_handler(PlanningCancelled)
async def planning_cancelled_handler(_request: Request, _exc: PlanningCancelled):
    return JSONResponse(
        status_code=409,
        content={
            "detail": {
                "code": "planning_cancelled",
                "message": "O calculo foi cancelado; o plano ativo nao foi alterado.",
            }
        },
    )


# The plan view is ~1.8 MB of JSON; compressed it reaches the browser well
# within the read timeout through the tunnel. Event streams are excluded.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Dataset-Id", "X-Plan-Revision"],
)
app.include_router(console_router)
app.include_router(data_router)
app.include_router(plans_router)
app.include_router(manual_plan_router)
app.include_router(robustness_router)
app.include_router(replan_router)
app.include_router(scenarios_router)


READ_ONLY_ALLOWED_MUTATIONS = {
    "/api/data/simulate",
    "/api/data/ctp",
    "/api/data/plan/move-preview",
    "/api/data/plan/move-preview-jobs",
    "/api/data/subcontracts/preview",
}


def _read_only_preview(method: str, path: str) -> bool:
    return method == "POST" and (
        path in READ_ONLY_ALLOWED_MUTATIONS
        or re.fullmatch(r"/api/data/skus/[^/]+/planning/preview", path) is not None
        or re.fullmatch(r"/api/data/plan/move-preview-jobs/[^/]+/cancel", path) is not None
    )


@app.middleware("http")
async def enforce_access_mode(request: Request, call_next):
    """Functional edit/view guard shared by UI and API clients."""

    access_mode = request.headers.get("x-access-mode", "edit").lower()
    if (
        access_mode == "view"
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and not _read_only_preview(request.method, request.url.path)
    ):
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Modo Consulta ativo. Muda para Editar para guardar, aplicar ou recalcular."
                )
            },
        )
    return await call_next(request)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class LoadRequest(BaseModel):
    isop_path: str
    config_path: str = "config/factory.yaml"
    master_path: str = "config/incompol.yaml"


@app.post("/api/copilot/chat")
async def copilot_chat(request: ChatRequest):
    """Chat with the copilot. LLM decides which tools to call."""
    provider = get_provider()
    system_prompt = build_system_prompt(state)
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    widgets = []
    tools_used = 0

    try:
        for _ in range(5):  # max 5 tool-call rounds
            response = await provider.chat_with_tools(messages, TOOLS, system_prompt)

            if response.tool_calls:
                # Append assistant message with tool calls
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

                for tc in response.tool_calls:
                    result_json, is_widget = await run_in_threadpool(
                        execute_tool, tc.name, tc.arguments
                    )
                    tools_used += 1

                    if is_widget:
                        try:
                            parsed = json.loads(result_json)
                            if "error" not in parsed:
                                widgets.append({"type": "dynamic_viz", "data": parsed})
                        except json.JSONDecodeError:
                            pass

                    # Append tool result for next LLM turn
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_json,
                        }
                    )

                continue

            # No tool calls — final response
            return {
                "response": response.content or "",
                "widgets": widgets,
                "tools_used": tools_used,
            }
    except Exception as exc:
        logger.warning("Copilot unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Copilot indisponível. O planeamento e dashboards continuam disponíveis.",
        ) from exc

    return {
        "response": "Limite de iterações atingido.",
        "widgets": widgets,
        "tools_used": tools_used,
    }


@app.post("/api/copilot/load")
async def load_isop(_request: LoadRequest):
    """Reject the unsafe path-based loader kept only for API compatibility."""
    raise HTTPException(
        410,
        (
            "Este carregamento foi desativado. Usa /api/data/load/prepare e "
            "/api/data/load/confirm para carregar o ficheiro e confirmar o "
            "estado atual das máquinas."
        ),
    )


@app.get("/api/copilot/health")
async def health():
    """Health check."""
    has_data = state.engine_data is not None
    backend = os.environ.get("PP1_LLM_BACKEND", "openai").lower()
    if backend == "ollama":
        copilot_available = bool(
            os.environ.get("PP1_OLLAMA_URL", "").strip()
            and os.environ.get("PP1_OLLAMA_MODEL", "").strip()
        )
        unavailable_reason = (
            "" if copilot_available else "O Copilot local ainda não está configurado."
        )
    else:
        api_key = os.environ.get("PP1_OPENAI_API_KEY", "").strip()
        copilot_available = api_key not in {
            "",
            "dummy",
            "sk-proj-YOUR_KEY_HERE",
        }
        unavailable_reason = (
            "" if copilot_available else "O Copilot ainda não tem uma chave configurada."
        )
    return {
        "status": "ok",
        "has_data": has_data,
        "plan_revision": state.plan_revision,
        "n_segments": len(state.segments),
        "dataset": state.dataset_info if has_data else None,
        "copilot": {
            "available": copilot_available,
            "backend": backend,
            "reason": unavailable_reason,
        },
    }
