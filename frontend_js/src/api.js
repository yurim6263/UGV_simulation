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
  const scenario = {
    ...replays[0].scenario,
    mission_id: set.mission_id,
    case: "서버 실행 · 그단스크 · 최적화 모드",
    turns: Math.max(...replays.map((r) => r.scenario.turns)),
    modes: replays.map((r) => r.scenario.modes[0]),
    overlays: [{ key: "total", label: "종합 위험도" }, { key: "mobility", label: "기동성 위험도" }, { key: "sensor", label: "센서 위험도" }],
  };
  return { scenario, raws: replays.map((r) => r.mode) };
}

export const overlayUrl = (kind, turn) => `${API_URL}/api/map/overlay/${kind}/${turn}.png`;

// ── AI 어시스턴트 ────────────────────────────────────────────────────────

export const assistantStatus = () => request("/api/assistant/status");
// 반환: { answer, evidences: [{id, tool, args, result, denied, error}], warnings, model, latency_ms }
export const askAssistant = (question) => request("/api/assistant/ask", { method: "POST", body: { question } });

// 문장 → 정찰 목표 제안 (지휘관 전용). 반환: { targets: [{lat, lon, recon_min, label}], assumptions, model, latency_ms }
export const draftMission = (text) => request("/api/assistant/mission-draft", { method: "POST", body: { text } });

// 상황 보고 초안 (근거 번호 포함). mode: balanced | recon | rapid. 통제관은 서버가 담당 제대 범위로 만든다.
export const requestSitrep = (mode) => request("/api/assistant/sitrep", { method: "POST", body: { mode } });
