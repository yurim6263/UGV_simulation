"""
frontend/api_client.py

백엔드 REST API 호출 모듈.
모든 함수는 동기(requests) 방식 — Solara 이벤트 핸들러에서 직접 호출.
"""

import os
import httpx

BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def _get(path: str, params: dict = None) -> dict | list:
    url = f"{BASE_URL}{path}"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _post(path: str, json: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, json=json)
        resp.raise_for_status()
        return resp.json()


# ── 시나리오 ──────────────────────────────────────

def fetch_scenarios() -> list[dict]:
    """GET /api/scenarios"""
    return _get("/api/scenarios")


# ── 임무 ──────────────────────────────────────────

def fetch_missions(scenario_id: str) -> list[dict]:
    """GET /api/v1/missions?scenario_id=..."""
    return _get("/api/v1/missions", params={"scenario_id": scenario_id})


def create_mission(payload: dict) -> dict:
    """POST /api/v1/missions"""
    return _post("/api/v1/missions", json=payload)


# ── 그리드 ────────────────────────────────────────

def fetch_grid(scenario_id: str, limit: int = 5000) -> list[dict]:
    """
    GET /api/grid?scenario_id=...&limit=...
    78,960행 전부를 지도에 렌더링하면 느리므로 limit으로 샘플링.
    """
    return _get("/api/grid", params={"scenario_id": scenario_id, "limit": limit})


# ── 기상 ──────────────────────────────────────────

def fetch_weather(scenario_id: str, time_step: str) -> list[dict]:
    """GET /api/weather?scenario_id=...&time_step=..."""
    return _get("/api/weather", params={"scenario_id": scenario_id, "time_step": time_step})


def fetch_time_steps(scenario_id: str) -> list[str]:
    """GET /api/weather/time-steps?scenario_id=... — 사용 가능한 time_step 목록"""
    return _get("/api/weather/time-steps", params={"scenario_id": scenario_id})


# ── 위험도 ────────────────────────────────────────

def fetch_risk(scenario_id: str, time_step: str) -> list[dict]:
    """GET /api/risk?scenario_id=...&time_step=..."""
    return _get("/api/risk", params={"scenario_id": scenario_id, "time_step": time_step})


# ── 시뮬레이션 결과 / 경로 ────────────────────────

def fetch_simulation_results(mission_id: int) -> list[dict]:
    """GET /api/simulation/status?mission_id=..."""
    return _get("/api/simulation/status", params={"mission_id": mission_id})


def fetch_optimal_paths(sim_id: int) -> list[dict]:
    """GET /api/routes/{sim_id}"""
    return _get(f"/api/routes/{sim_id}")


def start_simulation(mission_id: int) -> dict:
    """POST /api/simulation/start"""
    return _post("/api/simulation/start", json={"mission_id": mission_id})


def stop_simulation(mission_id: int) -> dict:
    """POST /api/simulation/stop"""
    return _post("/api/simulation/stop", json={"mission_id": mission_id})
