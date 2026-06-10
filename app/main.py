import asyncio
import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR
from app.db import init_db
from app.routes import families, pos, print_jobs, sales, scan, tally, templates as template_routes, variants, workflow


app = FastAPI(title="ShopBridge", version="0.1.0")
app.state.pos_cart_mutation_lock = asyncio.Lock()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class _SuppressPosCartAccessLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/pos/cart" not in message


logging.getLogger("uvicorn.access").addFilter(_SuppressPosCartAccessLogs())


def _is_pos_cart_mutation(path: str, method: str) -> bool:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    return (
        path == "/pos/scan"
        or path.startswith("/pos/cart")
        or path.startswith("/pos/checkout")
    )


@app.middleware("http")
async def serialize_pos_cart_mutations(request, call_next):
    if _is_pos_cart_mutation(request.url.path, request.method):
        async with request.app.state.pos_cart_mutation_lock:
            return await call_next(request)
    return await call_next(request)


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
