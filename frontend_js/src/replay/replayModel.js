// 재생 데이터 모델: 이동 기록(JSON) → 프레임별 상태 / 이벤트.
// 지도·패널은 이 모델에서 파생된 값만 읽는다 (HTML 안에 섞여 있던 로직을 분리한 것).

// 재생 데이터 출처: 서버 실행(API) / 팀원 시뮬레이션 기록(참조, 정적) / 엔진 실행(정적 사본)
export const REPLAY_SOURCES = {
  server: { label: "서버 실행", dir: null },
  reference: { label: "팀원 기록", dir: "replay" },
  engine: { label: "엔진 실행", dir: "replay_engine" },
};
export const replayBase = (source) => (REPLAY_SOURCES[source].dir ? `${import.meta.env.BASE_URL}${REPLAY_SOURCES[source].dir}` : null);

export const TEAM_UNIT = { Alpha: "1제대", Bravo: "2제대", Charlie: "3제대" };
export const USER_TEAM = { user1: "Alpha", user2: "Bravo", user3: "Charlie" };
export const TEAM_COLOR = { Alpha: "#f97316", Bravo: "#22d3ee", Charlie: "#f472b6" };
export const GRADE_COLOR = { G: "#2ecc71", A: "#f1c40f", R: "#e74c3c" };

const ACTION_LABEL = {
  MISSION: "기동", HOLD_PACE: "대열 대기", HOLD_EMERGENCY: "비상 대기", NO_AP: "행동력 소진",
  IDLE: "대기", TEAM_DONE: "제대 완료", SOS_SENSOR: "센서 고장", SOS_MOBILITY: "기동 고장",
  SOS_WAIT: "개입 대기", SOS_COMPLEX_FAILURE: "복합 고장", BLIND: "시야 상실", RECALL: "복귀", ARRIVED: "도착", PATROL: "정찰 중",
  NO_PATH: "경로 없음",
};
const SOS = new Set(["SOS_SENSOR", "SOS_MOBILITY", "SOS_COMPLEX_FAILURE"]);

export function agentLabel(agent) {
  const unit = TEAM_UNIT[agent.team];
  if (agent.kind === "UGV") return `${unit} UGV ${agent.no}`;
  if (agent.kind === "Manned") return `${unit} 유인기`;
  return `${unit} 운용자`;
}

export function actionLabel(action) {
  if (action.startsWith("INTERVENE->")) {
    const [, team, no] = action.split("->")[1].split("_"); // "UGV_Charlie_2"
    return `개입 → ${TEAM_UNIT[team] ?? team} UGV ${no}`;
  }
  return ACTION_LABEL[action] ?? action;
}

export function elapsedLabel(turn) {
  const min = turn * 10;
  const h = Math.floor(min / 60);
  return h ? `T+${h}시간 ${min % 60}분` : `T+${min}분`;
}

export function buildReplay(raw) {
  const agents = raw.agents;
  const steps = raw.steps.map((s) => ({
    turn: s[0], seq: s[1], agent: s[2], lat: s[3], lon: s[4], action: raw.actions[s[5]], ap: s[6],
    grade: raw.grades[s[7]], total: s[8], mob: s[9], sen: s[10],
    rain: s[11], swvl1: s[12], sde: s[13], fog: s[14], vis: s[15], order: s[0] * 100000 + s[1],
  }));
  steps.sort((a, b) => a.order - b.order);

  // 프레임 = 기록에 등장하는 (turn, seq) 의 고유 조합 (팀원 노트북과 같은 기준)
  const frameOrders = [...new Set(steps.map((s) => s.order))];
  const frames = frameOrders.map((order) => ({ order, turn: Math.floor(order / 100000), seq: order % 100000 }));
  const orderToFrame = new Map(frameOrders.map((o, i) => [o, i]));

  // 에이전트별 이동 기록과, 프레임마다 "지금까지 몇 개의 기록이 반영되었는지"
  const tracks = agents.map(() => []);
  const counts = new Int32Array(frames.length * agents.length);
  const running = new Int32Array(agents.length);
  let si = 0;
  frames.forEach((f, fi) => {
    while (si < steps.length && steps[si].order <= f.order) {
      tracks[steps[si].agent].push(steps[si]);
      running[steps[si].agent] += 1;
      si += 1;
    }
    counts.set(running, fi * agents.length);
  });

  // 이벤트: 상태가 새로 시작되는 시점만 (연속 기록은 1건으로)
  const events = [];
  const prev = new Map();
  for (const s of steps) {
    const before = prev.get(s.agent);
    prev.set(s.agent, s.action);
    if (before === s.action) continue;
    const a = agents[s.agent];
    const frame = orderToFrame.get(s.order);
    if (a.kind === "UGV" && SOS.has(s.action)) events.push({ type: "sos", frame, turn: s.turn, agent: s.agent, text: `${agentLabel(a)}: ${actionLabel(s.action)}`, team: a.team });
    else if (a.kind === "UGV" && s.action === "BLIND") events.push({ type: "blind", frame, turn: s.turn, agent: s.agent, text: `${agentLabel(a)}: 시야 상실`, team: a.team });
    else if (a.kind === "OP" && s.action.startsWith("INTERVENE")) events.push({ type: "intervene", frame, turn: s.turn, agent: s.agent, text: `${agentLabel(a)} ${actionLabel(s.action)}`, team: a.team });
    else if (a.kind === "Manned" && s.action === "ARRIVED") events.push({ type: "arrive", frame, turn: s.turn, agent: s.agent, text: `${TEAM_UNIT[a.team]} 정찰지 도착`, team: a.team });
  }

  return { mode: raw.mode, label: raw.label, agents, kpi: raw.kpi, frames, counts, tracks, events };
}

// 프레임 fi 시점의 에이전트별 마지막 기록 (아직 시작 전이면 null)
export function stateAt(model, fi, agentIdx) {
  const n = model.counts[fi * model.agents.length + agentIdx];
  return n ? model.tracks[agentIdx][n - 1] : null;
}

export function pathAt(model, fi, agentIdx) {
  const n = model.counts[fi * model.agents.length + agentIdx];
  const pts = [];
  let last = null;
  for (let i = 0; i < n; i += 1) {
    const s = model.tracks[agentIdx][i];
    if (!last || last[0] !== s.lat || last[1] !== s.lon) {
      last = [s.lat, s.lon];
      pts.push(last);
    }
  }
  return pts;
}

// 다른 모드로 바꿔도 같은 시점을 보도록: 같은 턴의 마지막 프레임으로 이동
export function frameForTurn(model, turn) {
  let idx = 0;
  model.frames.forEach((f, i) => { if (f.turn <= turn) idx = i; });
  return idx;
}

// 제대 범위(team)에 맞춘 KPI. team 이 없으면 전체(지휘관).
export function scopedKpi(model, team) {
  const k = model.kpi;
  const evs = team ? model.events.filter((e) => e.team === team) : model.events;
  const interventions = evs.filter((e) => e.type === "intervene").length;
  const ugvSteps = [];
  model.tracks.forEach((t, i) => {
    const a = model.agents[i];
    if (a.kind === "UGV" && (!team || a.team === team)) ugvSteps.push(...t);
  });
  const red = ugvSteps.length ? ugvSteps.filter((s) => s.grade === "R").length / ugvSteps.length : 0;
  if (!team) {
    return { arrived: k.ugv_arrived, total: k.ugv_total, turns: k.mission_turns, sos: k.sos_events, interventions, wait: k.wait_turns_mean, red };
  }
  const pt = k.per_team[team];
  if (!pt) return { arrived: 0, total: 0, turns: k.turns, sos: 0, interventions, wait: 0, red };   // 이 모드에 없는 제대
  return {
    arrived: pt.arrived, total: pt.ugv, turns: pt.arrive_turn == null ? k.turns : pt.arrive_turn + 1,
    sos: pt.sos, interventions, wait: pt.wait_turns_mean, red,
  };
}

export const KPI_ROWS = [
  ["도착 UGV", (k) => `${k.arrived}/${k.total}`, "대"],
  ["임무 소요 시간", (k) => k.turns * 10, "분"],
  ["SOS 발생", (k) => k.sos, "건"],
  ["운용자 개입", (k) => k.interventions, "회"],
  ["평균 개입 대기", (k) => Math.round(k.wait * 10), "분"],
  ["고위험(적색) 구간", (k) => Math.round(k.red * 100), "%"],
];

// 제대별 고위험(적색) 구간 비율: UGV 이동 기록 중 위험 등급 R 인 비율
export function teamRedRatio(model) {
  const out = {};
  for (const team of Object.keys(TEAM_UNIT)) {
    let red = 0;
    let all = 0;
    model.tracks.forEach((t, i) => {
      const a = model.agents[i];
      if (a.kind !== "UGV" || a.team !== team) return;
      all += t.length;
      red += t.filter((s) => s.grade === "R").length;
    });
    out[team] = all ? red / all : 0;
  }
  return out;
}
