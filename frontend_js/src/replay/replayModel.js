// 재생 데이터 모델: 이동 기록(JSON) → 프레임별 상태 / 이벤트.
// 지도·패널은 이 모델에서 파생된 값만 읽는다 (HTML 안에 섞여 있던 로직을 분리한 것).

// 재생 데이터 출처: 서버 실행(API) / 팀원 시뮬레이션 기록(참조, 정적) / 엔진 실행(정적 사본)
export const REPLAY_SOURCES = {
  server: { label: "서버 실행", dir: null, desc: "방금 서버가 계산한 결과입니다 (지휘관이 실행한 임무의 3개 모드)." },
  reference: { label: "팀원 기록", dir: "replay", desc: "팀원 시뮬레이터가 남긴 이동 기록입니다. 비교용 참조 자료이고 고정된 파일이라 임무를 바꿔도 변하지 않습니다." },
  engine: { label: "엔진 실행", dir: "replay_engine", desc: "이 프로젝트의 엔진이 같은 시나리오를 돌려 저장해 둔 결과입니다. 고정된 파일이라 임무를 바꿔도 변하지 않습니다." },
};
export const replayBase = (source) => (REPLAY_SOURCES[source].dir ? `${import.meta.env.BASE_URL}${REPLAY_SOURCES[source].dir}` : null);

// 보유 UGV 수 (임무 생성 때 정한 값, launchMission 의 기본값과 같다). 제대마다 1~3대를 투입한다.
export const FLEET_UGV = 9;

export const TEAM_UNIT = { Alpha: "1제대", Bravo: "2제대", Charlie: "3제대" };
export const USER_TEAM = { user1: "Alpha", user2: "Bravo", user3: "Charlie" };
// 색의 주인공은 위험 등급(G/A/R)이다. 제대 색은 위험 색과 겹치지 않게 파랑·보라·분홍으로 둔다.
export const TEAM_COLOR = { Alpha: "#4d8dff", Bravo: "#b07cff", Charlie: "#ff8fb1" };
export const GRADE_COLOR = { G: "#3fb68b", A: "#f2b544", R: "#f0644e" };

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
  // 절대 위험도: UGV 가 지나간 칸의 종합 위험도(0~1) 평균. 등급(G/A/R)과 달리 날씨 강도를 바꾸면 실제로 달라진다.
  const risk = ugvSteps.length ? ugvSteps.reduce((sum, s) => sum + s.total, 0) / ugvSteps.length : 0;
  if (!team) {
    return { arrived: k.ugv_arrived, total: k.ugv_total, turns: k.mission_turns, sos: k.sos_events, interventions, wait: k.wait_turns_mean, red, risk };
  }
  const pt = k.per_team[team];
  if (!pt) return { arrived: 0, total: 0, turns: k.turns, sos: 0, interventions, wait: 0, red, risk };   // 이 모드에 없는 제대
  return {
    arrived: pt.arrived, total: pt.ugv, turns: pt.arrive_turn == null ? k.turns : pt.arrive_turn + 1,
    sos: pt.sos, interventions, wait: pt.wait_turns_mean, red, risk,
  };
}

export const KPI_ROWS = [
  ["도착 UGV", (k) => `${k.arrived}/${k.total}`, "대"],
  ["임무 소요 시간", (k) => k.turns * 10, "분"],
  ["SOS 발생", (k) => k.sos, "건"],
  ["운용자 개입", (k) => k.interventions, "회"],
  ["평균 개입 대기", (k) => Math.round(k.wait * 10), "분"],
  ["평균 위험도", (k) => k.risk.toFixed(2), "(0~1)", "UGV 가 지나간 칸의 종합 위험도 평균. 절대값이라 날씨 강도에 따라 달라진다."],
  ["상대 고위험 구간", (k) => Math.round(k.red * 100), "%", "전 시간대 위험도의 상위 30% 구간(R)에서 보낸 UGV 기록 비율. 순위로 나눈 상대 등급이라 날씨 강도와 무관하다."],
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

// ── 제대별 타임라인 ──────────────────────────────────────────────────────
const GRADE_RANK = { G: 1, A: 2, R: 3 };

// 한 제대의 턴별 칸: 그 턴에 UGV 가 있던 칸 중 가장 나쁜 등급. 기록이 없으면 null, 제대가 도착한 뒤면 done.
// 이벤트: SOS / 운용자 개입 / 도착 (턴 번호 포함). 지도 재생과 같은 model 에서 만든다.
export function teamTimeline(model, team) {
  const turns = model.kpi.turns;
  const pt = model.kpi.per_team[team];
  const lastActive = pt?.arrive_turn == null ? turns - 1 : pt.arrive_turn;
  const worst = new Array(turns).fill(null);
  model.tracks.forEach((track, i) => {
    const a = model.agents[i];
    if (a.kind !== "UGV" || a.team !== team) return;
    for (const s of track) {
      if (s.turn >= turns) continue;
      if (!worst[s.turn] || GRADE_RANK[s.grade] > GRADE_RANK[worst[s.turn]]) worst[s.turn] = s.grade;
    }
  });
  const cells = worst.map((grade, turn) => ({ turn, grade, done: turn > lastActive }));
  const events = model.events.filter((e) => e.team === team && e.turn < turns)
    .map((e) => ({ type: e.type, turn: e.turn, frame: e.frame, text: e.text }));
  return { cells, events, turns };
}

// 모드 카드에 보여 줄 편성 글자: 지휘관은 "3-3-1 (7/9대)", 통제관은 자기 제대 "UGV 3대"
export function formationText(model, team) {
  const per = model.kpi.per_team;
  if (team) return per[team] ? `UGV ${per[team].ugv}대` : "-";
  const counts = Object.keys(TEAM_UNIT).filter((t) => per[t]).map((t) => per[t].ugv);
  return `${counts.join("-")} (${counts.reduce((a, b) => a + b, 0)}/${FLEET_UGV}대)`;
}
