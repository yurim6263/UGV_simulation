"""
backend/app/main.py

FastAPI 애플리케이션 진입점.

엔드포인트:
    GET  /health          — 헬스체크
    /api/auth/*           — 인증
    /api/missions/*       — 임무 관리
    /api/missions/*/runs  — run 생성
    /api/runs/*           — run 관리/조회
    /api/assets/*         — 데이터 에셋
    /api/runs/*/...       — 대시보드 조회
    WS   /ws/runs/{id}    — WebSocket 실시간 스트림
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
# from app.db.init_db import create_tables, seed_admin
# from app.db.session import AsyncSessionLocal
from app.db.init_db import init_db

logger = logging.getLogger(__name__)

_LTWR_DIR = Path(__file__).resolve().parents[1] / "data" / "ltwr_maps"


async def _ltwr_hourly_scanner():
    """매 정시에 ltwr_maps/ 폴더를 재스캔 (1시간 자동 갱신)."""
    from app.api.ltwr import scan_ltwr_dir
    while True:
        try:
            # 다음 정시까지 대기
            import time as _time
            secs = 3600 - (_time.time() % 3600)
            await asyncio.sleep(secs)
            scan_ltwr_dir()
            logger.info("LTWR hourly scan completed")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("LTWR hourly scan failed")
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # try:
    #     await create_tables()
    #     async with AsyncSessionLocal() as db:
    #         await seed_admin(db)
    # except Exception:
    #     logger.exception("DB initialization failed")
    try:
        await init_db()
    except Exception:
        logger.exception("DB initialization failed")

    # LTWR 1시간 갱신 스케줄러 시작
    scanner_task = asyncio.create_task(_ltwr_hourly_scanner())
    yield
    scanner_task.cancel()

app = FastAPI(
    title="파이브웨더즈 UGV 전술 지원 시스템",
    version="0.1.0",
    lifespan=lifespan,
)

# slowapi — rate limit 초과 시 429 응답 핸들러
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"요청이 너무 많습니다. 잠시 후 다시 시도하세요. ({exc.detail})"},
        headers={"Retry-After": "60"},
    )

# ── 보안 헤더 미들웨어 ────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """기본 보안 응답 헤더를 모든 응답에 추가.
    X-Frame-Options는 제외 — /sim-videos/, /sim-maps/ 등 정적 파일을
    Solara iframe 안에 임베드해야 하므로 프레임 차단 헤더를 붙이지 않는다."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# CORS — 환경변수 BACKEND_CORS_ORIGINS 기반 허용 목록
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 라우터 등록 ──────────────────────────────────────────

from app.api import auth, assets, dashboard, ltwr, missions, runs, websocket  # noqa: E402
from app.api import tactical_map  # 신규: 전술 맵 API
from app.api import operators      # 신규: 통제관 브리핑 API
from app.api import sim_map        # 신규: 시뮬레이션 결과 HTML 맵
from app.api import sim_video      # 신규: 시뮬레이션 결과 영상 API
from app.api import replay         # 신규: 이동 기록 재생 데이터 API

app.include_router(auth.router, prefix="/api")
app.include_router(missions.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(ltwr.router, prefix="/api")
app.include_router(websocket.router)
app.include_router(tactical_map.router, prefix="/api")  # 신규: /api/runs/{id}/map/*
app.include_router(operators.router, prefix="/api")     # 신규: /api/operators/*
app.include_router(sim_map.router, prefix="/api")       # 신규: /api/map/sim/*
app.include_router(sim_video.router, prefix="/api")     # 신규: /api/map/video/*
app.include_router(replay.router, prefix="/api")        # 신규: /api/runs/{id}/replay

# LTWR HTML 정적 파일 서빙 (/ltwr-maps/T0.html 등)
_LTWR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/ltwr-maps", StaticFiles(directory=str(_LTWR_DIR)), name="ltwr-maps")

# 시뮬레이션 결과 HTML 서빙 (/sim-maps/current.html)
_SIM_MAP_DIR = Path(__file__).resolve().parents[1] / "data" / "sim_map"
_SIM_MAP_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/sim-maps", StaticFiles(directory=str(_SIM_MAP_DIR)), name="sim-maps")

# 시뮬레이션 결과 영상 서빙 (/sim-videos/current.mp4)
_SIM_VIDEO_DIR = Path(__file__).resolve().parents[1] / "data" / "sim_video"
_SIM_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/sim-videos", StaticFiles(directory=str(_SIM_VIDEO_DIR)), name="sim-videos")


# ── 헬스체크 ─────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
