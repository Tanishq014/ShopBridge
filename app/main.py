import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR
from app.db import init_db
from app.routes import families, pos, print_jobs, sales, scan, tally, templates as template_routes, variants, workflow


app = FastAPI(title="ShopBridge", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class _SuppressPosCartAccessLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/pos/cart" not in message


logging.getLogger("uvicorn.access").addFilter(_SuppressPosCartAccessLogs())


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def home():
    return RedirectResponse("/new-stock", status_code=303)


app.include_router(workflow.router)
app.include_router(pos.router)
app.include_router(sales.router)
app.include_router(scan.router)
app.include_router(families.router)
app.include_router(variants.router)
app.include_router(template_routes.router)
app.include_router(print_jobs.router)
app.include_router(tally.router)
