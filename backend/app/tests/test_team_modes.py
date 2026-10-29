"""
backend/app/tests/test_team_modes.py

제대별 모드 지정과 통제관 권한 테스트.
지휘관이 제대마다 모드를 지정하면, 통제관은 담당 제대에 지정된 모드의 기록만 볼 수 있다 (화면이 아니라 서버가 막는다).
세 모드 기록은 손으로 구분할 수 있게 만든다: 모드 m, 제대 t 의 기록은 위도가 54.40 + 0.01*m + 0.001*t 이다.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.assistant.schema import ToolCall, ToolContext
from app.assistant.tools import execute_tool, role_of
from app.core.security import TokenPayload
from app.db.models.simulation_run import SimulationRun
from app.db.models.track import RunTrack
from app.db.session import AsyncSessionLocal

SERVER_MODES = ["balanced", "recon", "rapid"]         # m = 0, 1, 2
UI_MODES = ["balance", "explore", "rush"]
TEAMS = ["Alpha", "Bravo", "Charlie"]
USER = {"Alpha": "user1", "Bravo": "user2", "Charlie": "user3"}


async def seed(auth_client: AsyncClient, mission_id: int) -> dict[str, int]:
    """세 모드의 완료된 실행과 3개 제대의 기록을 만든다. {서버 모드: run_id}"""
    ids = {}
    for m, mode in enumerate(SERVER_MODES):
        resp = await auth_client.post(f"/api/missions/{mission_id}/runs", params={"mode": mode})
        assert resp.status_code == 201, resp.text
        run_id = resp.json()["id"]
        ids[mode] = run_id
        async with AsyncSessionLocal() as db:
            seq = 0
            rows = []
            for t, team in enumerate(TEAMS):
                for turn in range(3):
                    for agent in (f"Manned_{team}", f"UGV_{team}_1"):
                        seq += 1
                        rows.append(RunTrack(
                            run_id=run_id, seq_idx=seq, turn_idx=turn, agent_id=agent, action="MISSION", row=4 + turn, col=4 + t,
                            lat=54.40 + 0.01 * m + 0.001 * t, lon=18.40 + 0.001 * turn, ap=0, total=0.2, mob=0.2, sen=0.2, grade="G",
                        ))
            db.add_all(rows)
            await db.execute(update(SimulationRun).where(SimulationRun.id == run_id).values(status="COMPLETED"))
            await db.commit()
    return ids


async def set_modes(auth_client: AsyncClient, mission_id: int, modes: dict[str, str]):
    resp = await auth_client.put(f"/api/missions/{mission_id}/team-modes", json=modes)
    assert resp.status_code == 200, resp.text
    return resp.json()["team_modes"]


# ── 지정 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_team_modes_default_to_balance_and_can_be_changed_per_team(auth_client: AsyncClient, mission_id: int):
    got = (await auth_client.get(f"/api/missions/{mission_id}/team-modes")).json()["team_modes"]
    assert got == {"Alpha": "balance", "Bravo": "balance", "Charlie": "balance"}
    assert await set_modes(auth_client, mission_id, {"Bravo": "explore"}) == {"Alpha": "balance", "Bravo": "explore", "Charlie": "balance"}
    assert await set_modes(auth_client, mission_id, {"Charlie": "rush"}) == {"Alpha": "balance", "Bravo": "explore", "Charlie": "rush"}   # 보내지 않은 제대는 유지


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"Delta": "balance"}, {"Alpha": "turbo"}, {"Alpha": "balanced"}])
async def test_invalid_team_or_mode_is_rejected(auth_client: AsyncClient, mission_id: int, body):
    assert (await auth_client.put(f"/api/missions/{mission_id}/team-modes", json=body)).status_code == 422


@pytest.mark.asyncio
async def test_only_the_commander_can_assign_modes(login_as, mission_id: int, auth_client: AsyncClient):
    user1 = await login_as("user1")
    assert (await user1.put(f"/api/missions/{mission_id}/team-modes", json={"Alpha": "rush"})).status_code == 403
    assert (await auth_client.get(f"/api/missions/{mission_id}/team-modes")).json()["team_modes"]["Alpha"] == "balance"


@pytest.mark.asyncio
async def test_operator_sees_only_own_teams_assignment(login_as, mission_id: int, auth_client: AsyncClient):
    await set_modes(auth_client, mission_id, {"Alpha": "explore", "Bravo": "rush"})
    user2 = await login_as("user2")
    assert (await user2.get(f"/api/missions/{mission_id}/team-modes")).json()["team_modes"] == {"Bravo": "rush"}


# ── 통제관은 지정된 모드의 기록만 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_operator_can_read_only_the_run_of_the_assigned_mode(login_as, mission_id: int, auth_client: AsyncClient):
    ids = await seed(auth_client, mission_id)
    user1 = await login_as("user1")
    assert (await user1.get(f"/api/runs/{ids['balanced']}/replay")).status_code == 200          # 기본은 균형
    for other in ("recon", "rapid"):
        assert (await user1.get(f"/api/runs/{ids[other]}/replay")).status_code == 403

    await set_modes(auth_client, mission_id, {"Alpha": "explore"})
    assert (await user1.get(f"/api/runs/{ids['recon']}/replay")).status_code == 200
    assert (await user1.get(f"/api/runs/{ids['balanced']}/replay")).status_code == 403
    user2 = await login_as("user2")                                                             # 다른 제대는 영향이 없다
    assert (await user2.get(f"/api/runs/{ids['balanced']}/replay")).status_code == 200
    assert (await user2.get(f"/api/runs/{ids['recon']}/replay")).status_code == 403


@pytest.mark.asyncio
async def test_replay_of_the_assigned_run_has_only_own_team_and_reports_only_own_assignment(login_as, mission_id: int, auth_client: AsyncClient):
    ids = await seed(auth_client, mission_id)
    await set_modes(auth_client, mission_id, {"Bravo": "rush"})
    user2 = await login_as("user2")
    body = (await user2.get(f"/api/runs/{ids['rapid']}/replay")).json()
    assert {a["team"] for a in body["mode"]["agents"]} == {"Bravo"}
    assert body["scenario"]["team_modes"] == {"Bravo": "rush"}


@pytest.mark.asyncio
async def test_run_level_apis_outside_replay_are_guarded_too(login_as, mission_id: int, auth_client: AsyncClient):
    """재생 API 만 막으면 대시보드·지도 API 로 다른 모드의 run 을 읽을 수 있다. run_id 가 경로에 있는 API 는 같은 검사를 거친다."""
    ids = await seed(auth_client, mission_id)
    user1 = await login_as("user1")
    for path in ("/api/runs/{id}", "/api/runs/{id}/status", "/api/runs/{id}/kpis", "/api/runs/{id}/map/base"):
        denied = await user1.get(path.format(id=ids["recon"]))
        assert denied.status_code == 403, (path, denied.text)
        allowed = await user1.get(path.format(id=ids["balanced"]))
        assert allowed.status_code != 403, path
        assert (await auth_client.get(path.format(id=ids["recon"]))).status_code != 403, path          # 지휘관은 막히지 않는다


@pytest.mark.asyncio
async def test_latest_set_for_operator_lists_only_the_assigned_run(login_as, mission_id: int, auth_client: AsyncClient):
    ids = await seed(auth_client, mission_id)
    await set_modes(auth_client, mission_id, {"Alpha": "rush"})
    mine = (await (await login_as("user1")).get("/api/runs/latest-set")).json()
    assert [r["id"] for r in mine["runs"]] == [ids["rapid"]] and mine["team_modes"] == {"Alpha": "rush"} and mine["all_completed"]
    full = (await auth_client.get("/api/runs/latest-set")).json()
    assert {r["id"] for r in full["runs"]} == set(ids.values())
    assert full["team_modes"] == {"Alpha": "rush", "Bravo": "balance", "Charlie": "balance"}


# ── 제대별 합성 (재계산 없음) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assigned_replay_takes_each_teams_records_from_its_assigned_mode(mission_id: int, auth_client: AsyncClient):
    await seed(auth_client, mission_id)
    await set_modes(auth_client, mission_id, {"Alpha": "explore", "Bravo": "balance", "Charlie": "rush"})
    body = (await auth_client.get(f"/api/missions/{mission_id}/assigned-replay")).json()
    assert body["mode"]["mode"] == "assigned" and body["scenario"]["modes"] == [{"key": "assigned", "label": "지정 편성"}]
    assert body["scenario"]["team_modes"] == {"Alpha": "explore", "Bravo": "balance", "Charlie": "rush"}

    agents, cols = body["mode"]["agents"], body["mode"]["columns"]
    iag, ilat = cols.index("agent"), cols.index("lat")
    seen: dict[str, set[int]] = {}
    for step in body["mode"]["steps"]:
        team = agents[step[iag]]["team"]
        seen.setdefault(team, set()).add(round((step[ilat] - 54.40 - 0.001 * TEAMS.index(team)) / 0.01))
    assert seen == {"Alpha": {1}, "Bravo": {0}, "Charlie": {2}}              # 제대마다 지정된 모드(m)의 기록만 들어 있다
    assert body["mode"]["kpi"]["ugv_total"] == 3                             # 제대당 UGV 1대씩, 중복 없이
    cols_seq = cols.index("seq")
    assert max(step[cols_seq] for step in body["mode"]["steps"]) < 100_000          # 화면의 프레임 번호(턴 x 100000 + 순번)가 섞이지 않는다


@pytest.mark.asyncio
async def test_changing_an_assignment_changes_the_composition_without_new_runs(mission_id: int, auth_client: AsyncClient):
    ids = await seed(auth_client, mission_id)
    await set_modes(auth_client, mission_id, {"Alpha": "rush"})
    body = (await auth_client.get(f"/api/missions/{mission_id}/assigned-replay")).json()
    cols, agents = body["mode"]["columns"], body["mode"]["agents"]
    lat_alpha = {s[cols.index("lat")] for s in body["mode"]["steps"] if agents[s[cols.index("agent")]]["team"] == "Alpha"}
    assert len(lat_alpha) == 1 and next(iter(lat_alpha)) == pytest.approx(54.40 + 0.02, abs=1e-5)
    async with AsyncSessionLocal() as db:                                    # 실행(run)이 늘어나지 않았다
        from sqlalchemy import func, select
        assert (await db.execute(select(func.count()).select_from(SimulationRun))).scalar_one() == len(ids)


@pytest.mark.asyncio
async def test_assigned_replay_is_commander_only(login_as, mission_id: int, auth_client: AsyncClient):
    await seed(auth_client, mission_id)
    assert (await (await login_as("user1")).get(f"/api/missions/{mission_id}/assigned-replay")).status_code == 403


@pytest.mark.asyncio
async def test_assigned_replay_refuses_when_the_assigned_mode_is_not_finished(mission_id: int, auth_client: AsyncClient):
    ids = await seed(auth_client, mission_id)
    async with AsyncSessionLocal() as db:
        await db.execute(update(SimulationRun).where(SimulationRun.id == ids["recon"]).values(status="RUNNING"))
        await db.commit()
    await set_modes(auth_client, mission_id, {"Alpha": "explore"})
    assert (await auth_client.get(f"/api/missions/{mission_id}/assigned-replay")).status_code == 409


# ── AI 어시스턴트 ────────────────────────────────────────────────────────

def ctx(db, unit: str | None, role: str = "operator") -> ToolContext:
    user = TokenPayload(sub="2", role=role, unit=unit)
    return ToolContext(db=db, user=user, role=role_of(user))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", [
    ("compare_modes", {}), ("run_sql_analysis", {"report": "all"}), ("get_formation_plan", {}), ("get_optimization_results", {}),
])
async def test_mode_comparison_tools_are_denied_to_operators(mission_id: int, auth_client: AsyncClient, tool, args):
    await seed(auth_client, mission_id)
    async with AsyncSessionLocal() as db:
        denied = await execute_tool(ctx(db, "1제대"), ToolCall(tool, args), "E1")
        assert denied.denied, tool
        assert not (await execute_tool(ctx(db, None, "commander"), ToolCall(tool, args), "E1")).denied


@pytest.mark.asyncio
async def test_operator_tools_default_to_the_assigned_mode_and_refuse_others(mission_id: int, auth_client: AsyncClient):
    ids = await seed(auth_client, mission_id)
    await set_modes(auth_client, mission_id, {"Alpha": "explore"})
    async with AsyncSessionLocal() as db:
        mine = await execute_tool(ctx(db, "1제대"), ToolCall("get_run_summary", {}), "E1")
        assert mine.error is None and mine.result["run_id"] == ids["recon"]                 # mode 를 생략하면 지정된 모드
        for args in ({"mode": "balanced"}, {"mode": "rapid"}, {"run_id": ids["balanced"]}):
            other = await execute_tool(ctx(db, "1제대"), ToolCall("get_run_summary", args), "E2")
            assert other.error and "403" in other.error, args
        listed = await execute_tool(ctx(db, "1제대"), ToolCall("list_runs", {}), "E3")
        assert [r["run_id"] for r in listed.result["runs"]] == [ids["recon"]]
        full = await execute_tool(ctx(db, None, "commander"), ToolCall("list_runs", {}), "E4")
        assert len(full.result["runs"]) == 3


@pytest.mark.asyncio
async def test_operator_sitrep_for_an_unassigned_mode_is_refused(login_as, mission_id: int, auth_client: AsyncClient):
    await seed(auth_client, mission_id)
    user1 = await login_as("user1")
    resp = await user1.post("/api/assistant/sitrep", json={"mode": "rapid"})
    assert resp.status_code == 403, resp.text            # AI 키가 없어도(503) 모드 검사가 먼저다


@pytest.mark.asyncio
async def test_preview_map_images_stay_public_because_img_tags_cannot_send_tokens(client: AsyncClient):
    """모드 접근 검사를 run_id 가 없는 미리보기 API 에까지 걸면 목표 입력 화면의 지형/위험도 이미지가 401 로 깨진다 (실제로 한 번 그랬다)."""
    for path in ("/api/map/tactical/terrain-image", "/api/map/tactical/cost-image?layer=risk", "/api/map/tactical/bounds",
                 "/api/map/overlay/total/0.png", "/api/map/weather/info"):
        r = await client.get(path)
        assert r.status_code == 200, (path, r.status_code)
