"""
backend/app/api/tactical_map.py

전술 맵 데이터 API (신규 — 기존 dashboard.py / runs.py 비침범).

엔드포인트 (prefix: /api):
  ─ 미리보기 (run_id 불필요, CommanderInputPage 용) ─
  GET /api/map/tactical/terrain-image         — 지형 RGBA PNG (Leaflet imageOverlay)
  GET /api/map/tactical/cost-image?layer=risk — 비용 레이어 RGBA PNG
  GET /api/map/tactical/bounds                — 위경도 경계 JSON
  GET /api/map/tactical/leaflet-html          — Leaflet 전체 HTML (iframe srcdoc용)

  ─ run 연계 (시뮬레이션 결과 조회) ─
  GET /api/runs/{run_id}/map/base             — 정적 기반 레이어 JSON
  GET /api/runs/{run_id}/map/layer            — 동적 레이어 JSON
  GET /api/runs/{run_id}/map/commander        — 지휘관용 통합 맵 JSON
  GET /api/runs/{run_id}/map/operator         — 통제관용 통합 맵 JSON
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from app.api.deps import CurrentUser as _CurrentUserDep, run_path_guard
from app.db.schemas.tactical_map import (
    CommanderMapOut,
    MapBaseOut,
    MapLayerOut,
    OperatorMapOut,
)
from app.services import tactical_map_service as svc

router = APIRouter(tags=["tactical-map"])
# run_id 가 경로에 있는 API 만 모드 접근 검사를 건다. 미리보기(지형/위험도 이미지 등)는 <img> 가 인증 헤더를 보낼 수 없어 로그인 없이 열려 있어야 한다.
RUN_GUARD = [Depends(run_path_guard)]

CurrentUser = _CurrentUserDep  # TokenPayload (sub, role)


# ═══════════════════════════════════════════════════════════
# 미리보기 엔드포인트 (CommanderInputPage 용, 인증 불필요)
# ═══════════════════════════════════════════════════════════

@router.get(
    "/map/tactical/terrain-image",
    summary="지형 RGBA PNG (Leaflet imageOverlay용)",
    include_in_schema=True,
)
async def get_terrain_image():
    """
    lc_code 기반 지형 색상 PNG 반환.
    lru_cache로 최초 1회만 생성, 이후 메모리에서 즉시 반환.
    """
    try:
        data = svc.generate_terrain_png_bytes()
        return Response(content=data, media_type="image/png", headers={
            "Cache-Control": "public, max-age=3600",
        })
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"지형 이미지 생성 실패: {e}")


@router.get(
    "/map/tactical/buffer-image",
    summary="TIF 경로버퍼 RGBA PNG (Leaflet imageOverlay용)",
    include_in_schema=True,
)
async def get_buffer_image():
    """
    route_buffer_mask_5km_200m.tif → RGBA PNG.
    버퍼 내부: 반투명 황색, 외부: 투명.
    lru_cache로 최초 1회만 생성.
    """
    try:
        data = svc.generate_buffer_png_bytes()
        return Response(content=data, media_type="image/png", headers={
            "Cache-Control": "public, max-age=3600",
        })
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"버퍼 이미지 생성 실패: {e}")


@router.get(
    "/map/tactical/cost-image",
    summary="비용 레이어 PNG (위험도/기동성/센서)",
    include_in_schema=True,
)
async def get_cost_image(
    layer: Literal["risk", "mobility", "sensor"] = Query(
        default="risk",
        description="레이어 종류",
    ),
):
    """동적 비용 레이어 PNG 반환. 값 0→투명, 1→빨강."""
    try:
        data = svc.generate_cost_png_bytes(layer)
        return Response(content=data, media_type="image/png", headers={
            "Cache-Control": "no-cache",
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비용 이미지 생성 실패: {e}")


@router.get(
    "/grid/cells",
    summary="그리드 셀 JSON (Leaflet rectangle 렌더링용)",
)
async def get_grid_cells(
    layer: Literal["terrain", "risk", "mobility", "sensor"] = Query(
        default="terrain",
        description="레이어 종류: terrain(지형) | risk(위험도) | mobility(기동성) | sensor(센서)",
    ),
):
    """
    Leaflet rectangle 렌더링을 위한 셀 목록 반환.
    반환: {lat_step, lon_step, cells: [[lat, lon, r, g, b, a], ...]}
    """
    try:
        if layer == "terrain":
            return svc.get_terrain_cells_json()
        return svc.get_risk_cells_json(layer)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"셀 데이터 생성 실패: {e}")


@router.get(
    "/map/grid/html",
    response_class=HTMLResponse,
    summary="그리드 맵 Leaflet HTML (grid_view iframe src용)",
)
async def get_grid_map_html(
    layer: Literal["risk", "mobility", "sensor"] = Query(
        default="risk",
        description="비용 레이어 종류",
    ),
):
    """
    지형 + 선택 레이어를 rectangle로 렌더링하는 Leaflet HTML 반환.
    grid_view.py의 iframe src로 사용.
    """
    try:
        html = svc.generate_grid_map_html(layer)
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"그리드 맵 HTML 생성 실패: {e}")


@router.get(
    "/map/tactical/target-check",
    summary="목표 위치 검사 (수역, 고립된 땅, 작전 구역 밖). 핀을 놓을 때 화면이 부른다",
)
async def check_target_location(lat: float, lng: float):
    from app.simulation.target_check import check_target

    reason = check_target(lat, lng)
    return {"ok": reason is None, "reason": reason}


@router.get(
    "/map/tactical/bounds",
    summary="지도 위경도 경계 JSON",
)
async def get_bounds():
    """
    지형 데이터의 위경도 경계 반환.
    { min_lat, max_lat, min_lng, max_lng, center_lat, center_lng }
    """
    try:
        from app.simulation.loaders.map20km_loader import get_map_bounds
        return get_map_bounds()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/map/tactical/leaflet-html",
    response_class=HTMLResponse,
    summary="Leaflet 전체 HTML (iframe srcdoc 직접 embed용)",
)
async def get_leaflet_html(
    request: Request,
    unit1_lat: Optional[float] = Query(default=None, description="1제대 목적지 위도"),
    unit1_lng: Optional[float] = Query(default=None, description="1제대 목적지 경도"),
    unit2_lat: Optional[float] = Query(default=None),
    unit2_lng: Optional[float] = Query(default=None),
    unit3_lat: Optional[float] = Query(default=None),
    unit3_lng: Optional[float] = Query(default=None),
):
    """
    CommanderInputPage 지도 영역에 embedd할 Leaflet HTML 반환.
    백엔드 URL은 요청 origin에서 자동 감지.
    좌표 쿼리 파라미터가 있으면 마커가 초기 표시됨.
    """
    # 백엔드 베이스 URL 자동 감지
    backend_url = str(request.base_url).rstrip("/")

    markers = []
    coords = [
        ("u1", unit1_lat, unit1_lng, "1제대", "#e67e22"),
        ("u2", unit2_lat, unit2_lng, "2제대", "#3b82f6"),
        ("u3", unit3_lat, unit3_lng, "3제대", "#10b981"),
    ]
    for uid, lat, lng, label, color in coords:
        if lat is not None and lng is not None:
            markers.append({"id": uid, "lat": lat, "lng": lng, "label": label, "color": color})

    try:
        html = svc.generate_leaflet_html(backend_url=backend_url, markers=markers or None)
        return HTMLResponse(content=html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Leaflet HTML 생성 실패: {e}")


# ═══════════════════════════════════════════════════════════
# run 연계 엔드포인트 (시뮬레이션 결과 조회, JWT 필요)
# ═══════════════════════════════════════════════════════════

@router.get(
    "/runs/{run_id}/map/base",
    dependencies=RUN_GUARD,
    response_model=MapBaseOut,
    summary="정적 기반 레이어 조회",
)
async def get_map_base(run_id: int, current_user: CurrentUser):
    try:
        return svc.get_map_base(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"맵 데이터 로드 실패: {e}")


@router.get(
    "/runs/{run_id}/map/layer",
    dependencies=RUN_GUARD,
    response_model=MapLayerOut,
    summary="동적 레이어 조회 (위험도/기동성/센서)",
)
async def get_map_layer(
    run_id: int,
    current_user: CurrentUser,
    type: Literal["risk", "mobility", "sensor"] = Query(default="risk"),
):
    try:
        return svc.get_map_layer(run_id, type)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"레이어 로드 실패: {e}")


@router.get(
    "/runs/{run_id}/map/commander",
    dependencies=RUN_GUARD,
    response_model=CommanderMapOut,
    summary="지휘관용 통합 맵 (모든 제대 경로 포함)",
)
async def get_commander_map(run_id: int, current_user: CurrentUser):
    if current_user.role not in ("commander", "admin"):
        raise HTTPException(status_code=403, detail="지휘관 전용 엔드포인트입니다.")
    try:
        return svc.get_commander_map(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"지휘관 맵 로드 실패: {e}")


@router.get(
    "/runs/{run_id}/map/operator",
    dependencies=RUN_GUARD,
    response_model=OperatorMapOut,
    summary="통제관용 통합 맵 (자기 제대 경로만 포함)",
)
async def get_operator_map(
    run_id: int,
    current_user: CurrentUser,
    username: str = Query(description="통제관 사용자명 (user1/user2/user3)"),
):
    try:
        return svc.get_operator_map(run_id, username)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"통제관 맵 로드 실패: {e}")
