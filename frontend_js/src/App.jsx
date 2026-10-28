import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ImageOverlay, MapContainer, Marker, Tooltip } from "react-leaflet";
import { API_URL, assistantStatus, clearToken, createMission, draftMission, latestRunSet, login as apiLogin, planFormation, startRuns, waitForRuns } from "./api";
import { MAX_TARGETS, initialTargets, units } from "./data";
import { useReplay } from "./replay/useReplay";
import BaseMap from "./replay/BaseMap";
import ReplayMap from "./replay/ReplayMap";
import ReplayControls from "./replay/ReplayControls";
import TeamTimeline from "./replay/TeamTimeline";
import AssistantPanel from "./replay/AssistantPanel";
import FormationPanel from "./replay/FormationPanel";
import ForecastPanel from "./replay/ForecastPanel";
import WeatherLegend from "./replay/WeatherLegend";
import { MODE_FOCUS, pickRow, usePlan } from "./replay/usePlan";
import { clockText, teamLaunchTurn } from "./replay/clock";
import { AgentTable, EventList, KpiSummary } from "./replay/SidePanels";
import ParetoPanel from "./replay/ParetoPanel";
import { ICON_SCALE, startIcon, targetIcon } from "./replay/mapMarkers";
import { FLEET_UGV, GRADE_COLOR, TEAM_COLOR, TEAM_UNIT, USER_TEAM, elapsedLabel, formationText, scopedKpi, teamRedRatio } from "./replay/replayModel";

const MAP_BOUNDS = [[54.2977, 18.2640], [54.5209, 18.6479]];
const TEAM_ORDER = ["Alpha", "Bravo", "Charlie"];
const MODES = [
  { label: "균형", key: "balance" },
  { label: "정밀", key: "explore" },
  { label: "신속", key: "rush" },
];
const MODE_NAME = Object.fromEntries(MODES.map((m) => [m.key, m.label]));
const OVERLAY_LABEL = { total: "종합", mobility: "기동성", sensor: "센서", weather: "기상" };


function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <circle cx="14" cy="14" r="12" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="7" fill="none" stroke="currentColor" strokeOpacity=".6" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="2.5" fill="var(--risk-r)" />
    </svg>
  );
}

function Brand({ sub }) {
  return (
    <div className="brand">
      <Logo />
      <div><b>FIVE WEATHERS</b><span>{sub ?? "기상·환경 위험도 기반 전술 지휘결심체계"}</span></div>
    </div>
  );
}

// showRisk/onToggleRisk 를 주면 지도의 위험등급 색칠을 켜고 끄는 버튼이 붙는다 (입력 지도용)
function RiskLegend({ showRisk, onToggleRisk }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="legend">
      <b>상대 위험 등급 <button className="help-btn" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="등급 설명 펼치기">?</button></b>
      <div><i style={{ background: GRADE_COLOR.G }} />G 하위 30% · 안전 (옅게)</div>
      <div><i style={{ background: GRADE_COLOR.A }} />A 중간 40% · 주의</div>
      <div><i style={{ background: GRADE_COLOR.R }} />R 상위 30% · 위험</div>
      <small>전 시간대 기준 순위 · 날씨 강도와 무관</small>
      {open && (
        <p className="legend-help">
          G·A·R은 작전 구역의 모든 칸과 모든 시각의 위험도를 한 줄로 세워서 나눈 <b>상대 순위</b>입니다.
          비가 더 많이 와도 R이 늘어나지 않고, 모든 칸이 같이 위험해지면 그중 높은 쪽이 R이 됩니다.
          실제 위험의 크기는 등급이 아니라 <b>평균 위험도(0~1)</b> 값에서 확인하세요.
        </p>
      )}
      {onToggleRisk && (
        <button className={`btn block legend-toggle ${showRisk ? "" : "off"}`} onClick={onToggleRisk} aria-pressed={showRisk}>
          {showRisk ? "위험등급 색칠 숨기기" : "위험등급 색칠 보이기"}
        </button>
      )}
    </div>
  );
}

// ── 로그인 ───────────────────────────────────────────────────────────────

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event?.preventDefault();
    if (!username.trim() || !password) return setError("아이디와 비밀번호를 입력하세요.");
    setBusy(true);
    setError("");
    try {
      await onLogin(username.trim(), password);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <svg className="login-bg" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <radialGradient id="lg-r"><stop offset="0" stopColor="#f0644e" stopOpacity=".35" /><stop offset="1" stopColor="#f0644e" stopOpacity="0" /></radialGradient>
          <radialGradient id="lg-a"><stop offset="0" stopColor="#f2b544" stopOpacity=".25" /><stop offset="1" stopColor="#f2b544" stopOpacity="0" /></radialGradient>
          <radialGradient id="lg-g"><stop offset="0" stopColor="#3fb68b" stopOpacity=".22" /><stop offset="1" stopColor="#3fb68b" stopOpacity="0" /></radialGradient>
        </defs>
        <circle cx="1000" cy="260" r="360" fill="url(#lg-a)" />
        <circle cx="760" cy="640" r="320" fill="url(#lg-r)" />
        <circle cx="1180" cy="700" r="300" fill="url(#lg-g)" />
        <g fill="none" stroke="#fff" strokeOpacity=".07" strokeWidth="1.2">
          {[500, 560, 620, 680, 740, 800].map((y, i) => (
            <path key={y} d={`M0 ${y + 120 - i * 10}C220 ${y + 60 - i * 10} 360 ${y + 100 - i * 10} 520 ${y + 20 - i * 10}S800 ${y - 120 - i * 10} 1000 ${y - 80 - i * 10} 1300 ${y - 170 - i * 10} 1440 ${y - 240 - i * 10}`} />
          ))}
        </g>
        <g stroke="#fff" strokeOpacity=".05"><path d="M0 150H1440M0 300H1440M0 450H1440M0 600H1440M0 750H1440" /><path d="M240 0V900M480 0V900M720 0V900M960 0V900M1200 0V900" /></g>
      </svg>
      <section className="login-left">
        <div className="brand"><Logo size={30} /><b>FIVE WEATHERS</b></div>
        <div>
          <h1>기상·환경 위험도 기반<br />전술 지휘결심체계 지원시스템</h1>
          <p className="login-sub">정찰 MUM-T 편성과 경로를 추천하고, 통제관의 개입 부담까지 시뮬레이션으로 미리 확인합니다.</p>
        </div>
        <div className="login-pts">
          <div><b>위험도를 반영한 경로</b><span>이동 시간을 AP(행동력)로 계산해 날씨 위험이 큰 구간을 돌아갑니다.</span></div>
          <div><b>근거가 붙는 답변</b><span>AI 어시스턴트는 기록에서 조회한 숫자만 근거 번호와 함께 말합니다.</span></div>
          <div><b>역할별 보기</b><span>통제관은 담당 제대만, 지휘관은 전체를 봅니다.</span></div>
        </div>
      </section>
      <section className="login-right">
        <form className="login-card" onSubmit={submit}>
          <h2>로그인</h2>
          <p>부여받은 계정으로 접속하세요.</p>
          <label htmlFor="login-id">아이디</label>
          <input id="login-id" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
          <label htmlFor="login-pw">비밀번호</label>
          <input id="login-pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn primary block" disabled={busy}>{busy ? "로그인 중…" : "로그인"}</button>
          <div className="login-roles">
            <span><b>지휘관</b>전체 제대 · 임무 하달</span>
            <span><b>통제관</b>담당 제대 · 개입 지원</span>
          </div>
        </form>
      </section>
    </main>
  );
}

// ── 지휘관 목표 입력 ─────────────────────────────────────────────────────

const validPoint = (t) => Number.isFinite(Number(t.lat)) && Number.isFinite(Number(t.lng)) && t.lat !== "" && t.lng !== "";
// 작전 구역(서버 SimAlgoConfig.bounds 와 같다). 목표는 이 안에 있어야 한다.
const AREA = { minLat: 54.3006, maxLat: 54.5198, minLng: 18.2674, maxLng: 18.6444 };
const inArea = (lat, lng) => lat >= AREA.minLat && lat <= AREA.maxLat && lng >= AREA.minLng && lng <= AREA.maxLng;
const AREA_TEXT = `위도 ${AREA.minLat}~${AREA.maxLat}, 경도 ${AREA.minLng}~${AREA.maxLng}`;

// 끌어서 옮기는 목표 마커. 작전 구역 밖에 놓으면 원래 자리로 돌려놓는다.
function DragTarget({ index, target, onMove, onOut }) {
  const ref = useRef(null);
  const latest = useRef(target);
  latest.current = target;
  const handlers = useMemo(() => ({
    dragend() {
      const marker = ref.current;
      if (!marker) return;
      const { lat, lng } = marker.getLatLng();
      if (inArea(lat, lng)) {
        onMove(index, lat, lng);
      } else {
        marker.setLatLng([Number(latest.current.lat), Number(latest.current.lng)]);
        onOut();
      }
    },
  }), [index, onMove, onOut]);
  return (
    <Marker ref={ref} draggable position={[Number(target.lat), Number(target.lng)]} icon={targetIcon(TEAM_COLOR[TEAM_ORDER[index]], index + 1)} eventHandlers={handlers} zIndexOffset={400}>
      <Tooltip direction="top" offset={[0, Math.round(-24 * ICON_SCALE)]}>{index + 1}제대 목표 · 끌어서 옮기기</Tooltip>
    </Marker>
  );
}

function InputMap({ targets, showRisk, onMove, onOut }) {
  return (
    <MapContainer bounds={MAP_BOUNDS} boundsOptions={{ padding: [4, 4] }} zoomControl attributionControl={false} zoomSnap={0.1} zoomDelta={0.5}>
      <BaseMap />
      <ImageOverlay url={`${API_URL}/api/map/tactical/terrain-image`} bounds={MAP_BOUNDS} opacity={0.55} />
      {showRisk && <ImageOverlay url={`${API_URL}/api/map/tactical/cost-image?layer=risk`} bounds={MAP_BOUNDS} opacity={0.6} />}
      <Marker position={[54.48, 18.32]} icon={startIcon()} interactive={false}>
        <Tooltip permanent direction="top" offset={[0, Math.round(-34 * ICON_SCALE)]}>출발지</Tooltip>
      </Marker>
      {targets.map((t, i) => validPoint(t) && <DragTarget key={i} index={i} target={t} onMove={onMove} onOut={onOut} />)}
    </MapContainer>
  );
}

// 문장으로 목표를 채운다 (AI 제안). 입력칸만 채우고 실행은 사람이 누른다.
function MissionTextBox({ targets, setTargets }) {
  const [on, setOn] = useState(null);          // null: 확인 중, false: AI 꺼짐
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);      // { error } 또는 { assumptions, filled }
  useEffect(() => { assistantStatus().then((s) => setOn(!!s.enabled)).catch(() => setOn(false)); }, []);

  async function fill() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setNote(null);
    try {
      const draft = await draftMission(text.trim());
      setTargets((cur) => {
        const next = [...cur];
        draft.targets.forEach((t) => {
          const i = t.team - 1;                  // 제대 번호대로 채운다 (건너뛴 제대는 그대로 둔다)
          if (i >= 0 && i < MAX_TARGETS) next[i] = { lat: String(t.lat), lng: String(t.lon), recon: String(t.recon_min) };
        });
        return Array.from({ length: next.length }, (_, i) => next[i] ?? initialTargets[i]);   // 빈 자리는 기본 목표로 메운다
      });
      setNote({ assumptions: draft.assumptions, teams: draft.targets.map((t) => t.team).sort() });
    } catch (e) {
      setNote({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2 className="h">문장으로 입력 <small className="beta">AI 제안</small></h2>
      <div className="card">
        {on === false ? (
          <p className="hint nomargin">AI 어시스턴트가 꺼져 있어 좌표를 직접 입력해야 합니다. 서버 <code>backend/.env</code>의 <code>GEMINI_API_KEY</code>를 설정하면 켜집니다.</p>
        ) : (
          <>
            <textarea
              className="nl-text" value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={3}
              placeholder="예: 1제대는 그디니아, 2제대는 공항 근처, 3제대는 출발지에서 북동쪽 3km. 정찰은 각 30분"
              aria-label="임무 문장" disabled={on === null}
            />
            <button className="btn block" onClick={fill} disabled={busy || !text.trim() || on === null}>{busy ? "해석하는 중…" : "목표 채우기"}</button>
            {note?.error && <p className="form-error" role="alert">{note.error}</p>}
            {note && !note.error && (
              <div className="nl-note" role="status">
                <b>{note.teams.map((t) => `${t}제대`).join(", ")} 목표를 채웠습니다. 좌표를 확인한 뒤 실행하세요.</b>
                {note.assumptions.length > 0 && <ul>{note.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>}
              </div>
            )}
            <p className="hint">장소 좌표는 대략적인 값(±1km)입니다. AI는 입력칸만 채우고 임무를 실행하지 않습니다.</p>
          </>
        )}
      </div>
    </section>
  );
}

function CommanderInputPage({ account, targets, setTargets, onSubmit, onLogout }) {
  const update = (i, field, value) => setTargets((current) => current.map((t, k) => (k === i ? { ...t, [field]: value } : t)));
  const [showRisk, setShowRisk] = useState(true);
  const [message, setMessage] = useState("");              // 지도 안내 문구 (작전 구역 밖으로 끌었을 때 등)
  const timer = useRef(null);
  const say = (text) => {
    setMessage(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(""), 4000);
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  const [formError, setFormError] = useState("");

  // 지도에서 끌어 놓은 위치를 입력칸에 반영한다 (입력칸을 고치면 마커가 따라 움직인다: 같은 상태를 공유)
  const move = useCallback((i, lat, lng) => {
    setFormError("");
    setTargets((current) => current.map((t, k) => (k === i ? { ...t, lat: lat.toFixed(5), lng: lng.toFixed(5) } : t)));
  }, [setTargets]);
  const outOfArea = useCallback(() => say(`작전 구역 밖입니다. 원래 위치로 되돌렸습니다. (${AREA_TEXT})`), []);
  const add = () => {
    if (targets.length >= MAX_TARGETS) return;
    const base = initialTargets[targets.length];
    setTargets((current) => [...current, { ...base }]);
    say(`${targets.length + 1}제대 목표를 추가했습니다. 지도에서 끌어 위치를 정하세요.`);
  };
  const remove = (i) => {
    if (targets.length <= 1) return;
    setTargets((current) => current.filter((_, k) => k !== i));
  };

  function submit() {
    const bad = targets.findIndex((t) => !validPoint(t) || !inArea(Number(t.lat), Number(t.lng)));
    if (bad >= 0) return setFormError(`${bad + 1}제대 목표가 비었거나 작전 구역 밖입니다. (${AREA_TEXT})`);
    setFormError("");
    onSubmit();
  }

  const n = targets.length;
  const used = n * 3;                                       // 제대당 UGV 최대 3대
  return (
    <main className="app">
      <header className="top">
        <Brand sub="임무 계획 · 목표를 입력하고 시뮬레이션을 실행합니다" />
        <div className="top-right"><span className="chip">{account.label} · {account.username}</span><button className="icon-btn" onClick={onLogout} aria-label="로그아웃"><LogoutIcon /></button></div>
      </header>
      <div className="body two">
        <section className="stage">
          <div className="map-fill"><InputMap targets={targets} showRisk={showRisk} onMove={move} onOut={outOfArea} /></div>
          <div className="map-legend-pos"><RiskLegend showRisk={showRisk} onToggleRisk={() => setShowRisk(!showRisk)} /></div>
          <div className={`tip ${message ? "warn" : ""}`} role="status">{message || "번호 핀을 끌어서 목표 위치를 정하세요. 입력칸과 서로 연동됩니다. 배경은 시작 시각의 위험도이고, 오른쪽 버튼으로 색칠을 숨길 수 있습니다(지형은 그대로)."}</div>
        </section>
        <aside className="side">
          <MissionTextBox targets={targets} setTargets={setTargets} />
          <section>
            <h2 className="h">정찰 목표 <small className="beta">{n}곳 · 최대 {MAX_TARGETS}곳</small></h2>
            <div className="card">
              {targets.map((t, i) => (
                <div className="tgt" key={i}>
                  <span className="no" style={{ background: TEAM_COLOR[TEAM_ORDER[i]] }}>{i + 1}</span>
                  <label className="f"><small>위도</small><input value={t.lat} onChange={(e) => update(i, "lat", e.target.value)} inputMode="decimal" aria-label={`${i + 1}제대 목표 위도`} /></label>
                  <label className="f"><small>경도</small><input value={t.lng} onChange={(e) => update(i, "lng", e.target.value)} inputMode="decimal" aria-label={`${i + 1}제대 목표 경도`} /></label>
                  <label className="f"><small>정찰(분)</small><input value={t.recon} onChange={(e) => update(i, "recon", e.target.value)} inputMode="numeric" aria-label={`${i + 1}제대 정찰 시간`} /></label>
                  <button className="icon-btn sm" onClick={() => remove(i)} disabled={n <= 1} aria-label={`${i + 1}제대 목표 삭제`} title={n <= 1 ? "목표는 최소 1곳" : "이 목표 삭제"}>×</button>
                </div>
              ))}
              <button className="btn block" onClick={add} disabled={n >= MAX_TARGETS}>+ 목표 추가</button>
              {n < MAX_TARGETS && (
                <p className="hint">
                  목표 {n}곳이면 {n}개 제대만 출동합니다 (제대당 UGV 최대 3대, 최대 {used}대 투입).
                  보유 9대 중 {9 - used}대는 쓰지 않고, {Array.from({ length: MAX_TARGETS - n }, (_, k) => `${n + k + 1}제대`).join("·")}는 이번 임무에 배정이 없습니다.
                </p>
              )}
            </div>
          </section>
          <p className="hint nomargin">실행하면 먼저 목표 위치에 맞게 제대별 UGV 투입 대수(1~3대, 보유 9대)를 계산한 뒤, 균형·정밀·신속 3가지 모드를 시뮬레이션합니다. 목표는 작전 구역(그단스크 인근) 안이어야 합니다.</p>
          {formError && <p className="form-error" role="alert">{formError}</p>}
          <button className="btn primary block big" onClick={submit}>시뮬레이션 실행</button>
        </aside>
      </div>
    </main>
  );
}

// 지휘관이 입력한 목표로 임무를 만들고, 목표 위치에 맞게 제대별 UGV 수(1~3대)를 계산한 뒤, 3개 모드의 시뮬레이션을 서버에서 실행한다
function LaunchPage({ targets, onDone, onBack }) {
  const [step, setStep] = useState(0);                 // 0 임무 생성, 1 편성 계산, 2 모드 실행
  const [plan, setPlan] = useState(null);              // 편성 계산 진행 상태
  const [runPct, setRunPct] = useState(0);
  const [modesDone, setModesDone] = useState(0);
  const [error, setError] = useState("");
  // 개발 모드(StrictMode)는 효과를 한 번 정리했다가 다시 실행한다. 임무가 두 번 만들어지지 않도록 시작은 한 번만 하고,
  // "화면이 아직 있는가"는 시작 여부와 따로 추적한다 (둘을 섞으면 정리 때 꺼진 값이 되살아나지 않아 진행 표시가 멈춘다).
  const started = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const parsed = targets.map((t) => ({
          lat: Number(t.lat), lon: Number(t.lng), patrolSec: Math.max(0, Number(t.recon || 0)) * 60,
        }));
        if (parsed.some((t) => !Number.isFinite(t.lat) || !Number.isFinite(t.lon) || t.lat === 0 || t.lon === 0)) {
          throw new Error("목표의 위도와 경도를 모두 숫자로 입력하세요.");
        }
        const missionId = await createMission({ targets: parsed });
        if (!mounted.current) return;
        setStep(1);
        await planFormation(missionId, (s) => { if (mounted.current) setPlan(s); });
        if (!mounted.current) return;
        setStep(2);
        await startRuns(missionId);
        const set = await waitForRuns((s) => {
          if (!mounted.current) return;
          setModesDone(s.runs.filter((r) => r.status === "COMPLETED").length);
          setRunPct(Math.round(s.runs.reduce((n, r) => n + r.progress_pct, 0) / Math.max(1, s.runs.length)));
        });
        if (mounted.current) onDone(set);
      } catch (e) {
        if (mounted.current) setError(e.message);
      }
    })();
    // 의도적으로 한 번만 실행한다 (targets/onDone 이 바뀌어도 임무를 다시 만들지 않는다)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const planPct = plan && plan.total ? Math.round((plan.done / plan.total) * 100) : 0;
  const steps = [
    ["임무 만들기", step > 0 ? "완료" : "진행 중"],
    ["편성 계산", step > 1 ? (plan?.cached ? "저장된 결과 사용" : "완료") : step === 1 ? (plan?.cached ? "저장된 결과 사용" : `${planPct}% (${plan?.done ?? 0}/${plan?.total ?? "?"})`) : "대기"],
    ["모드별 시뮬레이션", step === 2 ? `${modesDone}/3 모드 완료 · ${runPct}%` : "대기"],
  ];
  const pct = step === 0 ? 3 : step === 1 ? 5 + planPct * 0.55 : 60 + runPct * 0.4;

  return (
    <main className="center-page">
      {error ? (
        <div className="launch">
          <h1>시뮬레이션을 실행하지 못했습니다</h1>
          <p className="form-error" role="alert">{error}</p>
          <button className="btn primary" onClick={onBack}>목표 입력으로 돌아가기</button>
        </div>
      ) : (
        <div className="launch">
          <Logo size={40} />
          <h1>{step === 1 ? "목표 위치에 맞는 편성을 계산하는 중" : step === 2 ? "모드별 시뮬레이션 실행 중" : "임무를 만드는 중"}</h1>
          <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${Math.max(4, pct)}%` }} /></div>
          <ol className="steps">
            {steps.map(([name, state], i) => (
              <li key={name} className={i < step ? "done" : i === step ? "now" : ""}><span>{name}</span><em>{state}</em></li>
            ))}
          </ol>
          <p className="hint">제대마다 UGV를 1~3대 투입하는 모든 조합을 시험해서 균형·정밀·신속 모드의 편성을 정합니다. 직접 입력한 목표는 1분 정도, 기본 목표는 저장된 결과를 써서 더 빨리 끝납니다.</p>
        </div>
      )}
    </main>
  );
}

// ── 메인 대시보드 ────────────────────────────────────────────────────────

function LogoutIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" />
    </svg>
  );
}

function remainingLabel(turns, turn) {
  const min = Math.max(0, (turns - turn - 1) * 10);
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}:00`;
}

function Seg({ value, options, onChange, disabled, hints }) {
  return (
    <div className="seg">
      {options.map(([key, label]) => (
        <button key={key} className={value === key ? "on" : ""} onClick={() => onChange(key)} disabled={disabled} title={hints?.[key]}>{label}</button>
      ))}
    </div>
  );
}

function MainDashboard({ account, onLogout }) {
  const replay = useReplay();
  const [tab, setTab] = useState("summary");
  const [notice, setNotice] = useState("");
  const notify = (text) => { setNotice(text); setTimeout(() => setNotice(""), 2400); };

  // 통제관은 자기 제대만, 지휘관은 전체를 본다
  const myTeam = account.role === "commander" ? null : USER_TEAM[account.username];
  const allowedTeams = myTeam ? [myTeam] : null;
  const { model, models, scenario } = replay;
  const { plan } = usePlan(scenario?.mission_id, !myTeam);          // 편성 계산은 지휘관만 읽을 수 있다
  const turn = model ? model.frames[replay.frame].turn : 0;
  const redByTeam = useMemo(() => (model ? teamRedRatio(model) : {}), [model]);
  const shownTeams = TEAM_ORDER.filter((t) => model?.kpi.per_team[t] && (!allowedTeams || allowedTeams.includes(t)));
  const modeKpi = useMemo(
    () => (models ? Object.fromEntries(Object.entries(models).map(([k, m]) => [k, scopedKpi(m, myTeam)])) : {}),
    [models, myTeam],
  );
  const tabs = [["summary", "요약"], ["events", "이벤트"], ["units", "UGV"], ...(myTeam ? [] : [["formation", "편성"], ["pareto", "최적화"]]), ["forecast", "예보"], ["ai", "AI 어시스턴트"]];
  const { teamModes } = replay;
  const assignText = shownTeams.map((t) => `${TEAM_UNIT[t]} ${MODE_NAME[teamModes[t]] ?? "-"}`).join(" · ");

  return (
    <main className="app">
      {notice && <div className="toast" role="status">{notice}</div>}
      <header className="top">
        <Brand />
        <span className="chip"><i className="dot" style={{ background: GRADE_COLOR.G }} />{scenario ? scenario.case : "불러오는 중"}</span>
        <div className="top-right">
          {model && scenario?.start_time && (
            <div className="remaining" title="시뮬레이션 데이터의 시각입니다. 실제 현재 시각이 아닙니다."><small>시나리오 시각</small><span className="num">{clockText(scenario.start_time, turn * 10)}</span></div>
          )}
          <div className="remaining"><small>남은 시간</small><span className="num">{model ? remainingLabel(model.kpi.turns, turn) : "--:--:--"}</span></div>
          <span className="chip">{account.label} · {account.username}</span>
          <button className="icon-btn" onClick={onLogout} aria-label="로그아웃"><LogoutIcon /></button>
        </div>
      </header>

      <div className="body three">
        <aside className="rail">
          {myTeam && model && (
            <section>
              <h2 className="h">임무 모드</h2>
              <div className="mode on static">
                <span className="n">{MODE_NAME[replay.mode] ?? replay.mode}<small>지휘관 지정</small></span>
                <span className="d">{MODE_FOCUS[replay.mode]?.desc}</span>
              </div>
            </section>
          )}
          {!myTeam && (
          <section>
            <h2 className="h">임무 모드</h2>
            {models?.assigned && (
              <button className={`mode assigned ${replay.mode === "assigned" ? "on" : ""}`} onClick={() => replay.setMode("assigned")}>
                <span className="n">지정 편성{replay.mode === "assigned" && <small>선택됨</small>}</span>
                <span className="d">제대마다 지정한 모드의 기록을 합친 결과</span>
                <span className="mode-form">{assignText}</span>
                <span className="mode-form" title="제대별 UGV 투입 대수">편성 <b className="num">{formationText(models.assigned, myTeam)}</b></span>
                {modeKpi.assigned && <span className="m"><span>도착 <b className="num">{modeKpi.assigned.arrived}/{modeKpi.assigned.total}</b></span><span>SOS <b className="num">{modeKpi.assigned.sos}</b></span></span>}
              </button>
            )}
            {models?.assigned && <p className="hint tight sub-h">모드별 결과 (비교용)</p>}
            {MODES.map((m) => {
              const k = modeKpi[m.key];
              const focus = MODE_FOCUS[m.key];
              const row = pickRow(plan, m.key);
              return (
                <button key={m.key} className={`mode ${replay.mode === m.key ? "on" : ""}`} onClick={() => replay.setMode(m.key)} disabled={!model}>
                  <span className="n">{m.label}{replay.mode === m.key && <small>선택됨</small>}</span>
                  <span className="d">{focus.desc}</span>
                  {row && <span className="focus" title={`${focus.tip} · 편성 계산의 평균(시드 ${row.seeds}개)`}>{focus.label} <b className="num">{focus.get(row)}</b></span>}
                  {models?.[m.key] && <span className="mode-form" title="제대별 UGV 투입 대수 (목표 위치에 맞게 계산)">편성 <b className="num">{formationText(models[m.key], myTeam)}</b></span>}
                  {k && <span className="m"><span>도착 <b className="num">{k.arrived}/{k.total}</b></span><span>SOS <b className="num">{k.sos}</b></span></span>}
                </button>
              );
            })}
          </section>
          )}
          {!myTeam && model && models?.assigned && (
            <section>
              <h2 className="h">제대별 모드 지정</h2>
              {shownTeams.map((t) => (
                <div className="assign" key={t}>
                  <i style={{ background: TEAM_COLOR[t] }} />
                  <span>{TEAM_UNIT[t]}</span>
                  <Seg value={teamModes[t]} options={MODES.map((m) => [m.key, m.label])} onChange={(v) => replay.assignMode(t, v)} />
                </div>
              ))}
              {replay.assignError && <p className="form-error" role="alert">{replay.assignError}</p>}
              <p className="hint tight">바꿔도 다시 계산하지 않고 저장된 모드별 기록을 제대별로 합칩니다. 제대끼리 서로 영향이 없다는 가정입니다. 통제관은 자기 제대에 지정된 모드만 볼 수 있습니다.</p>
            </section>
          )}
          <section>
            <h2 className="h">지도 표시</h2>
            <Seg value={replay.overlay} options={Object.entries(OVERLAY_LABEL)} onChange={replay.setOverlay} />
          </section>
          {model && (
            <section>
              <h2 className="h">제대</h2>
              {shownTeams.map((t) => {
                const pt = model.kpi.per_team[t];
                const on = replay.teams[t];
                const Tag = myTeam ? "div" : "button";
                return (
                  <Tag key={t} className={`team ${on ? "" : "off"}`} onClick={myTeam ? undefined : () => replay.toggleTeam(t)} aria-pressed={myTeam ? undefined : on}>
                    <i style={{ background: TEAM_COLOR[t] }} />
                    <span className="tn">{TEAM_UNIT[t]} {t}</span>
                    <em>UGV {pt.ugv}</em>
                    <span className="bars">
                      <span className="bar-row" title="이 제대 UGV 중 도착한 비율">
                        <small>도착</small><span className="bar"><b style={{ width: `${Math.round((pt.arrived / pt.ugv) * 100)}%`, background: TEAM_COLOR[t] }} /></span><em>{Math.round((pt.arrived / pt.ugv) * 100)}%</em>
                      </span>
                      <span className="bar-row" title="UGV 이동 기록 중 상대 등급 R(상위 30%) 칸에서 보낸 비율">
                        <small>고위험</small><span className="bar"><b style={{ width: `${Math.round((redByTeam[t] ?? 0) * 100)}%`, background: "var(--risk-r)" }} /></span><em>{Math.round((redByTeam[t] ?? 0) * 100)}%</em>
                      </span>
                    </span>
                    <small>{pt.poi ? `POI-${pt.poi}` : "-"} · {pt.arrive_turn == null ? "미도착" : `도착 ${elapsedLabel(pt.arrive_turn + 1)}`}</small>
                  </Tag>
                );
              })}
              <p className="hint tight">도착: 제대 UGV 중 임무를 마친 비율. 고위험: 이동 기록 중 상대 등급 R 칸에서 보낸 비율.</p>
            </section>
          )}
          {account.role === "commander" && <button className="btn primary block big push" onClick={() => notify(`임무를 하달했습니다 (${assignText})`)} disabled={!model}>임무 하달</button>}
        </aside>

        <div className="center-col">
          <section className="stage">
            {replay.error && <p className="status error">{replay.error}</p>}
            {replay.loading && <p className="status">재생 데이터를 불러오는 중…</p>}
            {model && (
              <>
                <div className="map-fill replay-map"><ReplayMap replay={replay} allowedTeams={allowedTeams} /></div>
                <div className="map-legend-pos">{replay.overlay === "weather" ? <WeatherLegend turn={turn} /> : <RiskLegend />}</div>
                <div className="turn"><small>경과</small><b className="num">{elapsedLabel(turn)}</b><small className="num">턴 {turn + 1} / {model.kpi.turns}</small></div>
                <ReplayControls replay={replay} allowedTeams={allowedTeams} />
              </>
            )}
          </section>
          {model && <TeamTimeline replay={replay} allowedTeams={allowedTeams} />}
        </div>

        <aside className="right">
          <div className="tabs" role="tablist">
            {tabs.map(([key, label]) => (
              <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}>{label}</button>
            ))}
          </div>
          <div className="panel">
            {model && tab === "summary" && <KpiSummary replay={replay} team={myTeam} />}
            {model && tab === "events" && <EventList replay={replay} allowedTeams={allowedTeams} />}
            {model && tab === "units" && <AgentTable replay={replay} allowedTeams={allowedTeams} />}
            {tab === "formation" && model && <FormationPanel replay={replay} />}
            {tab === "pareto" && <ParetoPanel onPickMode={replay.setMode} />}
            {tab === "forecast" && model && <ForecastPanel replay={replay} allowedTeams={allowedTeams} />}
            {tab === "ai" && <AssistantPanel role={account.role} mode={replay.mode === "assigned" ? "balance" : replay.mode} />}
          </div>
        </aside>
      </div>
    </main>
  );
}

// ── 통제관 브리핑 ────────────────────────────────────────────────────────

function UserMissionPage({ account, onConfirm, onLogout }) {
  // 서버가 돌려준 이 제대의 시뮬레이션 결과(균형 모드)를 보여준다. 통제관은 자기 제대 기록만 받는다.
  const replay = useReplay();
  const team = USER_TEAM[account.username];
  const unit = units.find((item) => item.key === account.username);
  const model = replay.model;                              // 통제관에게는 지정된 모드의 기록 하나만 온다
  const modeLabel = replay.scenario?.modes?.[0]?.label ?? "-";
  const pt = model?.kpi.per_team[team];
  const poi = pt?.poi ? replay.scenario?.pois.find((p) => p.id === pt.poi) : null;
  const dash = (v) => (v === null || v === undefined ? "-" : v);
  const unassigned = replay.unassigned;                  // 목표가 3곳보다 적으면 뒤쪽 제대는 출동하지 않는다
  const launchTurn = model && team && pt ? teamLaunchTurn(model, team) : null;
  const startIso = replay.scenario?.start_time;
  return (
    <main className="app">
      <header className="top">
        <Brand />
        <div className="top-right"><span className="chip">{account.label} · {account.username}</span><button className="icon-btn" onClick={onLogout} aria-label="로그아웃"><LogoutIcon /></button></div>
      </header>
      <div className="brief">
        <div className="brief-head">
          <div><h1>{unit?.name ?? account.unit} 통제관 임무 브리핑</h1><p>지휘관이 하달한 임무 정보를 확인하세요. 이 화면에는 담당 제대 기록만 표시됩니다.</p></div>
          {team && <span className="team-tag" style={{ borderColor: TEAM_COLOR[team], color: TEAM_COLOR[team] }}><i style={{ background: TEAM_COLOR[team] }} />담당 제대 · {team}</span>}
        </div>
        {replay.error && <p className="form-error" role="alert">{replay.error}</p>}
        {unassigned && <p className="unassigned" role="status"><b>배정 없음</b> 이번 임무에서 {unit?.name ?? account.unit}는 출동하지 않습니다. 지휘관이 목표를 3곳보다 적게 입력했습니다.</p>}
        <div className="brief-cols">
          <section className="card"><h2 className="h">{account.unit} 자산 현황</h2>
            <p className="kv"><span>통제관 수</span><b className="num">1</b></p>
            <p className="kv"><span>운용 UGV 수</span><b className="num">{dash(pt?.ugv)}</b></p>
            <p className="kv"><span>목표 위도</span><b className="num">{dash(poi?.lat)}</b></p>
            <p className="kv"><span>목표 경도</span><b className="num">{dash(poi?.lon)}</b></p>
          </section>
          <section className="card"><h2 className="h">시뮬레이션 결과 · {modeLabel} (1회 실행)</h2>
            <p className="kv"><span>도착 UGV</span><b className="num">{pt ? `${pt.arrived} / ${pt.ugv}` : "-"}</b></p>
            <p className="kv"><span>SOS 발생</span><b className="num risk">{pt ? `${pt.sos}건` : "-"}</b></p>
            <p className="kv"><span>평균 개입 대기</span><b className="num">{pt ? `${Math.round(pt.wait_turns_mean * 10)}분` : "-"}</b></p>
          </section>
          <section className="card"><h2 className="h">임무 정보</h2>
            <p className="kv"><span>임무 모드 (지휘관 지정)</span><b className="amber">{modeLabel}</b></p>
            <p className="kv"><span>출발 시각</span><b className="num">{launchTurn === null ? "-" : elapsedLabel(launchTurn)}</b></p>
            <p className="kv"><span>도착 시각 (시뮬레이션)</span><b className="num">{pt ? (pt.arrive_turn == null ? "미도착" : elapsedLabel(pt.arrive_turn + 1)) : "-"}</b></p>
            {startIso && <p className="kv"><span>시나리오 시각</span><b className="num">{clockText(startIso, (launchTurn ?? 0) * 10)} → {pt?.arrive_turn == null ? "-" : clockText(startIso, (pt.arrive_turn + 1) * 10)}</b></p>}
          </section>
        </div>
        <button className="btn primary big center" onClick={onConfirm} disabled={!model}>통제관 메인 화면으로</button>
      </div>
    </main>
  );
}

export default function App() {
  const [account, setAccount] = useState(null);
  const [page, setPage] = useState("login");
  const [targets, setTargets] = useState(initialTargets);

  // 서버 로그인. 통제관은 지휘관의 시뮬레이션이 끝나 있어야 들어갈 수 있다.
  async function login(username, password) {
    const next = await apiLogin(username, password);
    if (next.role === "controller") {
      try {
        const set = await latestRunSet();
        if (!set.all_completed) throw new Error("not ready");
      } catch (e) {
        clearToken();
        if (e.status === 0) throw e;                          // 서버 연결 실패는 그대로 알린다
        throw new Error("아직 지휘관이 임무 입력 및 시뮬레이션을 완료하지 않았습니다.");
      }
    }
    setAccount(next);
    setPage(next.role === "commander" ? "input" : "briefing");
  }
  function logout() { clearToken(); setAccount(null); setPage("login"); }
  if (!account || page === "login") return <LoginPage onLogin={login} />;
  if (page === "input") return <CommanderInputPage account={account} targets={targets} setTargets={setTargets} onSubmit={() => setPage("loading")} onLogout={logout} />;
  if (page === "loading") return <LaunchPage targets={targets} onDone={() => setPage("main")} onBack={() => setPage("input")} />;
  if (page === "briefing") return <UserMissionPage account={account} onConfirm={() => setPage("main")} onLogout={logout} />;
  return <MainDashboard account={account} onLogout={logout} />;
}
