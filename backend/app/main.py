"""FastAPI application — REST API (OpenAPI at /api/docs)."""
from .api.common import *  # noqa: F401,F403 — names the app setup, middleware and startup use


app = FastAPI(title="Permit Review AI", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                   allow_headers=["*"])


@app.middleware("http")
async def _login_gate(request: Request, call_next):
    """With the app login on, every /api call except health, login and the AI agent's needs a valid session."""
    path = request.url.path
    if settings.login_required and path.startswith("/api") and not path.startswith(_OPEN_API):
        from .login import COOKIE, read_session
        if not read_session(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "נדרשת כניסה למערכת"}, status_code=401)
    return await call_next(request)


@app.on_event("startup")
def _startup():
    run_migrations()
    from . import committees
    with SessionLocal() as s0:                      # national committee register, loaded once
        committees.ensure_imported(s0)
        from . import hierarchy                     # national → district → committee → authority, and terminology
        hierarchy.build(s0)
        s0.commit()
    if settings.typing_worker:
        import threading
        threading.Thread(target=_typing_worker, daemon=True, name="typing-worker").start()
    if settings.onboarding_worker:
        import threading
        threading.Thread(target=authorities.worker, args=(SessionLocal,), daemon=True, name="onboarding-worker").start()

# ------------------------------------------------------------------ routers (URLs unchanged)
from .api import cases, identity, monitor, platform, rules  # noqa: E402

for _r in (identity, cases, rules, monitor, platform):
    app.include_router(_r.router)
