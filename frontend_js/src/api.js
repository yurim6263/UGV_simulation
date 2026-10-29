// 백엔드(FastAPI) 연동. 토큰은 메모리에만 두어 새로고침하면 다시 로그인한다 (저장소에 남기지 않는다).
export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";

let token = null;
export const hasToken = () => token !== null;
export const clearToken = () => { token = null; };

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, `서버에 연결할 수 없습니다 (${API_URL}). 백엔드를 실행했는지 확인하세요.`);
  }
  if (!res.ok) {
    let detail = `요청이 실패했습니다 (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg).join(", ");
    } catch { /* 본문이 JSON 이 아니면 기본 메시지 */ }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? null : res.json();
}

// ── 인증 ─────────────────────────────────────────────────────────────────

// 서버의 역할(commander / operator)을 화면의 역할(commander / controller)로 옮긴다
export async function login(username, password) {
  const { access_token: accessToken } = await request("/api/auth/login", { method: "POST", body: { username, password }, auth: false });
  token = accessToken;
  const me = await request("/api/auth/me");
  const isCommander = me.role === "commander";
  return {
    username: me.username,
    role: isCommander ? "commander" : "controller",
    unit: me.assigned_unit,
    label: isCommander ? "지휘관" : `${me.assigned_unit ?? ""} 통제관`.trim(),
  };
}

// ── 임무 실행 ────────────────────────────────────────────────────────────

const MODES = [["balance", "balanced"], ["explore", "recon"], ["rush", "rapid"]];   // 화면 모드 → 서버 모드

// 1) 임무와 목표를 만든다 (보유 UGV 9대, 제대마다 투입 대수는 편성 계산이 정한다)
export async function createMission({ targets, totalUgv = 9, durationMin = 240, start = [54.48, 18.32] }) {
  const mission = await request("/api/missions", {
    method: "POST",
    body: {
      name: `임무 ${new Date().toLocaleString("ko-KR")}`, total_ugv: totalUgv, max_ugv_count: totalUgv,
      mission_duration_min: durationMin, departure_lat: start[0], departure_lon: start[1],
    },
  });
  await request(`/api/missions/${mission.id}/targets`, {
    method: "POST",
    body: targets.map((t, i) => ({ seq: i + 1, lat: t.lat, lon: t.lon, patrol_duration_sec: t.patrolSec })),
  });
  return mission.id;
}

// 2) 편성 계산 (제대당 UGV 1~3대). 시작하고 끝날 때까지 진행률을 알려 준다. 같은 입력의 저장된 결과가 있으면 바로 끝난다.
export const getPlan = (missionId) => request(`/api/missions/${missionId}/plan`);

export async function planFormation(missionId, onProgress, { intervalMs = 1000, timeoutMs = 900000 } = {}) {
  let state = await request(`/api/missions/${missionId}/plan`, { method: "POST" });
  onProgress?.(state);
  const deadline = Date.now() + timeoutMs;
  while (state.status === "RUNNING" || state.status === "PENDING") {
    if (Date.now() > deadline) throw new ApiError(504, "편성 계산이 제한 시간 안에 끝나지 않았습니다.");
    await new Promise((r) => setTimeout(r, intervalMs));
    state = await getPlan(missionId);
    onProgress?.(state);
  }
  if (state.status !== "COMPLETED") throw new ApiError(500, state.error || "편성 계산에 실패했습니다.");
  return state;
}

// 3) 계산된 편성으로 3개 모드의 시뮬레이션을 동시에 시작한다
export async function startRuns(missionId) {
  const runs = [];
  for (const [, serverMode] of MODES) {
    runs.push(await request(`/api/missions/${missionId}/runs?mode=${serverMode}`, { method: "POST" }));
  }
  await Promise.all(runs.map((r) => request(`/api/runs/${r.id}/start`, { method: "POST" })));
  return missionId;
}

export const latestRunSet = () => request("/api/runs/latest-set");

// 모든 run 이 끝날 때까지 기다린다. 실패/취소된 run 이 있으면 즉시 예외.
export async function waitForRuns(onProgress, { intervalMs = 1000, timeoutMs = 300000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const set = await latestRunSet();
    onProgress?.(set);
    const bad = set.runs.find((r) => r.status === "FAILED" || r.status === "CANCELLED");
    if (bad) throw new ApiError(500, `시뮬레이션이 ${bad.status === "FAILED" ? "실패" : "취소"}되었습니다. 목표 좌표가 작전 구역(그단스크 인근) 안인지 확인하세요.`);
    if (set.all_completed) return set;
    if (Date.now() > deadline) throw new ApiError(504, "시뮬레이션이 제한 시간 안에 끝나지 않았습니다.");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// 가장 최근 임무의 3개 모드 재생 데이터 (통제관은 서버가 자기 제대만 돌려준다)
export async function fetchServerReplay() {
  const set = await latestRunSet();
  if (!set.all_completed) throw new ApiError(409, "시뮬레이션이 아직 끝나지 않았습니다.");
  let replays;
  try {
    replays = await Promise.all(set.runs.map((r) => request(`/api/runs/${r.id}/replay`)));
  } catch (e) {
    // 목표가 3곳보다 적으면 뒤쪽 제대는 편성되지 않아 서버가 404("제대의 기록이 없습니다")로 답한다. 오류가 아니라 "배정 없음"이다.
    if (e.status === 404 && e.message.includes("제대의 기록이 없습니다")) e.unassigned = true;
    throw e;
  }
  // 지휘관에게는 제대마다 지정한 모드의 기록을 합친 "지정 편성"도 온다 (통제관은 담당 제대 하나라 필요 없다)
  const assigned = Object.keys(set.team_modes ?? {}).length > 1 ? await fetchAssigned(set.mission_id) : null;
  const scenario = {
    ...replays[0].scenario,
    mission_id: set.mission_id,
    team_modes: set.team_modes ?? {},
    case: "서버 실행 · 그단스크 · 최적화 모드",
    turns: Math.max(...replays.map((r) => r.scenario.turns)),
    modes: replays.map((r) => r.scenario.modes[0]),
    overlays: [{ key: "total", label: "종합 위험도" }, { key: "mobility", label: "기동성 위험도" }, { key: "sensor", label: "센서 위험도" }],
  };
  return { scenario, raws: [...(assigned ? [assigned.mode] : []), ...replays.map((r) => r.mode)] };
}

// 제대별 모드 지정 (지휘관). 모드는 화면 이름(balance | explore | rush).
export const setTeamModes = (missionId, teamModes) => request(`/api/missions/${missionId}/team-modes`, { method: "PUT", body: teamModes });
// 제대마다 지정한 모드의 기록을 합친 재생 데이터 (재계산 없음)
export const fetchAssigned = (missionId) => request(`/api/missions/${missionId}/assigned-replay`);

// 지도 표시 "기상"은 원시 기상(ERA5)으로 만든 지표 이미지, 나머지는 위험도(G/A/R) 이미지
// 등급 기준이 바뀌면 GRADE_VERSION 을 올린다 (서버가 이미지를 1시간 캐시하므로 주소가 같으면 브라우저가 옛 색을 계속 쓴다)
export const GRADE_VERSION = 2;
export const overlayUrl = (kind, turn) => (kind === "weather" ? `${API_URL}/api/map/weather/${turn}.png` : `${API_URL}/api/map/overlay/${kind}/${turn}.png?v=${GRADE_VERSION}`);
// 목표 위치 검사 (수역, 고립된 땅, 구역 밖). 반환 { ok, reason }. 서버가 못 답하면 막지 않는다(실행 때 서버가 다시 검사한다).
export const checkTarget = (lat, lng) => request(`/api/map/tactical/target-check?lat=${lat}&lng=${lng}`, { auth: false }).catch(() => ({ ok: true, reason: null }));
export const weatherInfo = () => request("/api/map/weather/info", { auth: false });

// ── AI 어시스턴트 ────────────────────────────────────────────────────────

export const assistantStatus = () => request("/api/assistant/status");
// 반환: { answer, evidences: [{id, tool, args, result, denied, error}], warnings, model, latency_ms }
export const askAssistant = (question) => request("/api/assistant/ask", { method: "POST", body: { question } });

// 문장 → 정찰 목표 제안 (지휘관 전용). 반환: { targets: [{lat, lon, recon_min, label}], assumptions, model, latency_ms }
export const draftMission = (text) => request("/api/assistant/mission-draft", { method: "POST", body: { text } });

// 상황 보고 초안 (근거 번호 포함). mode: balanced | recon | rapid. 통제관은 서버가 담당 제대 범위로 만든다.
export const requestSitrep = (mode) => request("/api/assistant/sitrep", { method: "POST", body: { mode } });
