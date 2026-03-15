"""PP1 Backend — FastAPI server."""

import json
import os
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from isop_parser import parse_isop
from llm_engine import LLMEngine
from pydantic import BaseModel
from scheduler import Scheduler

app = FastAPI(title="PP1 — ProdPlan ONE", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
state = {
    "scheduler": None,
    "llm_engine": None,
    "isop_loaded": False,
    "references": [],
    "machines": [],
    "metadata": {},
}


def get_scheduler() -> Scheduler:
    if state["scheduler"] is None:
        raise HTTPException(status_code=400, detail="ISOP não carregado. Faça upload primeiro.")
    return state["scheduler"]


def get_llm() -> LLMEngine:
    if state["llm_engine"] is None:
        raise HTTPException(
            status_code=400, detail="LLM não inicializado. Carregue o ISOP primeiro."
        )
    return state["llm_engine"]


# === ISOP Upload ===


@app.post("/api/upload-isop")
async def upload_isop(file: UploadFile = File(...)):
    """Upload and parse ISOP Excel file."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser .xlsx ou .xls")

    # Save temp file
    temp_path = f"/tmp/isop_{file.filename}"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        references, machines, metadata = parse_isop(temp_path)

        # Initialize scheduler with today's date from ISOP
        # The ISOP date is 2026-02-27, use that as "today" for the demo
        scheduler = Scheduler(references, machines, today="2026-02-27")
        summary = scheduler.schedule_all()

        # Initialize LLM
        api_key = os.environ.get("OPENAI_API_KEY")
        llm_engine = None
        if api_key:
            llm_engine = LLMEngine(scheduler, api_key)

        state["scheduler"] = scheduler
        state["llm_engine"] = llm_engine
        state["isop_loaded"] = True
        state["references"] = references
        state["machines"] = machines
        state["metadata"] = metadata

        return {
            "status": "ok",
            "metadata": metadata,
            "summary": summary,
            "llm_available": llm_engine is not None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar ISOP: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/api/load-default")
async def load_default():
    """Load the default ISOP file."""
    # Check multiple possible locations
    paths = [
        "ISOP_default.xlsx",
        "/mnt/user-data/uploads/ISOP__Nikufra_27_2-2.xlsx",
    ]
    default_path = None
    for p in paths:
        if os.path.exists(p):
            default_path = p
            break

    if not default_path:
        raise HTTPException(status_code=404, detail="Ficheiro ISOP default não encontrado.")

    try:
        references, machines, metadata = parse_isop(default_path)
        scheduler = Scheduler(references, machines, today="2026-02-27")
        summary = scheduler.schedule_all()

        api_key = os.environ.get("OPENAI_API_KEY")
        llm_engine = None
        if api_key:
            llm_engine = LLMEngine(scheduler, api_key)

        state["scheduler"] = scheduler
        state["llm_engine"] = llm_engine
        state["isop_loaded"] = True
        state["references"] = references
        state["machines"] = machines
        state["metadata"] = metadata

        return {
            "status": "ok",
            "metadata": metadata,
            "summary": summary,
            "llm_available": llm_engine is not None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


# === Schedule ===


@app.get("/api/schedule")
async def get_schedule():
    """Get current production schedule."""
    scheduler = get_scheduler()
    return {
        "schedule": scheduler.get_schedule_json(),
        "machines": list(scheduler.machines.keys()),
    }


@app.get("/api/schedule/{machine_id}")
async def get_machine_schedule(machine_id: str):
    """Get schedule for a specific machine."""
    scheduler = get_scheduler()
    all_jobs = scheduler.get_schedule_json()
    machine_jobs = [j for j in all_jobs if j["machine"] == machine_id]
    return {"machine": machine_id, "jobs": machine_jobs}


# === Alerts ===


@app.get("/api/alerts")
async def get_alerts(severity: str | None = None):
    """Get production alerts."""
    scheduler = get_scheduler()
    alerts = scheduler.get_alerts_json()
    if severity and severity != "all":
        alerts = [a for a in alerts if a["severity"] == severity]
    return {"alerts": alerts, "total": len(alerts)}


# === References ===


@app.get("/api/references")
async def get_references():
    """Get all references with priority info."""
    scheduler = get_scheduler()
    return {"references": scheduler.get_references_json()}


@app.get("/api/references/{ref_id}")
async def get_reference_detail(ref_id: str):
    """Get detailed info about a reference."""
    scheduler = get_scheduler()
    info = scheduler.explain_ref(ref_id)
    return {"detail": json.loads(info)}


# === Machines ===


@app.get("/api/machines")
async def get_machines():
    """Get machine load summary."""
    scheduler = get_scheduler()
    load = json.loads(scheduler.get_machine_load())
    return {"machines": load}


# === Chat / LLM ===


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat with the LLM assistant."""
    llm = get_llm()
    result = llm.chat(request.message)

    # If schedule was updated, include fresh data
    response_data = {
        "response": result["response"],
        "tool_calls": result["tool_calls"],
        "schedule_updated": result["schedule_updated"],
    }

    if result["schedule_updated"]:
        scheduler = get_scheduler()
        response_data["schedule"] = scheduler.get_schedule_json()
        response_data["alerts"] = scheduler.get_alerts_json()

    return response_data


# === Dashboard Summary ===


@app.get("/api/dashboard")
async def get_dashboard():
    """Get dashboard summary data."""
    scheduler = get_scheduler()
    alerts = scheduler.get_alerts_json()
    schedule = scheduler.get_schedule_json()
    load = json.loads(scheduler.get_machine_load())

    # Count by severity
    severity_counts = {"atraso": 0, "red": 0, "yellow": 0}
    for a in alerts:
        if a["severity"] in severity_counts:
            severity_counts[a["severity"]] += 1

    # KPIs
    total_refs = len(scheduler.references)
    refs_with_shortage = sum(1 for r in scheduler.references.values() if r.first_shortage_date)
    total_jobs = len(schedule)
    avg_utilization = sum(m["utilization_pct"] for m in load.values()) / len(load) if load else 0

    return {
        "kpis": {
            "total_references": total_refs,
            "refs_with_shortage": refs_with_shortage,
            "total_scheduled_jobs": total_jobs,
            "avg_machine_utilization": round(avg_utilization, 1),
            "alerts_atraso": severity_counts["atraso"],
            "alerts_red": severity_counts["red"],
            "alerts_yellow": severity_counts["yellow"],
        },
        "machines": load,
        "top_alerts": alerts[:10],
        "schedule_summary": {
            m: len([j for j in schedule if j["machine"] == m]) for m in scheduler.machines
        },
    }


# === Health ===


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "isop_loaded": state["isop_loaded"],
        "llm_available": state["llm_engine"] is not None,
    }


# Serve frontend
@app.get("/")
async def root():
    return FileResponse("static/index.html")


# Static files (must be after all API routes)
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
