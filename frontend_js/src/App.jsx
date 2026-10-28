import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { ImageOverlay, MapContainer, Marker, Tooltip } from "react-leaflet";
import { API_URL, assistantStatus, clearToken, draftMission, launchMission, latestRunSet, login as apiLogin, waitForRuns } from "./api";
import { initialTargets, ltwrMaps, units } from "./data";
import { useReplay } from "./replay/useReplay";
import BaseMap from "./replay/BaseMap";
import ReplayMap from "./replay/ReplayMap";
import ReplayControls from "./replay/ReplayControls";
import TeamTimeline from "./replay/TeamTimeline";
import AssistantPanel from "./replay/AssistantPanel";
import { AgentTable, EventList, KpiSummary } from "./replay/SidePanels";
import ParetoPanel from "./replay/ParetoPanel";
import { GRADE_COLOR, REPLAY_SOURCES, TEAM_COLOR, TEAM_UNIT, USER_TEAM, elapsedLabel, scopedKpi, teamRedRatio } from "./replay/replayModel";

const MAP_BOUNDS = [[54.2977, 18.2640], [54.5209, 18.6479]];
const TEAM_ORDER = ["Alpha", "Bravo", "Charlie"];
const MODES = [
  { label: "균형", key: "balance", desc: "도착과 안전의 균형" },
  { label: "정밀", key: "explore", desc: "수색 범위 우선" },
  { label: "신속", key: "rush", desc: "빠른 도착 우선" },
];
const OVERLAY_LABEL = { total: "종합", mobility: "기동성", sensor: "센서" };

function pinIcon(color, label) {
  return L.divIcon({
    html: `<div class="pin" style="background:${color}">${label}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    className: "leaflet-marker-wrapper",
  });
}
const startIcon = L.divIcon({ html: '<div class="pin start"></div>', iconSize: [18, 18], iconAnchor: [9, 9], className: "leaflet-marker-wrapper" });

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

function RiskLegend() {
  return (
    <div className="legend">
      <b>상대 위험 등급</b>
      <div><i style={{ background: GRADE_COLOR.G }} />G 하위 30% (옅게)</div>
      <div><i style={{ background: GRADE_COLOR.A }} />A 중간 40%</div>
      <div><i style={{ background: GRADE_COLOR.R }} />R 상위 30%</div>
      <small>전 시간대 기준 순위 · 날씨 강도와 무관</small>
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

function InputMap({ targets }) {
  return (
    <MapContainer bounds={MAP_BOUNDS} boundsOptions={{ padding: [8, 8] }} zoomControl attributionControl={false}>
      <BaseMap />
      <ImageOverlay url={`${API_URL}/api/map/tactical/terrain-image`} bounds={MAP_BOUNDS} opacity={0.55} />
      <ImageOverlay url={`${API_URL}/api/map/tactical/cost-image?layer=risk`} bounds={MAP_BOUNDS} opacity={0.6} />
      <Marker position={[54.48, 18.32]} icon={startIcon} interactive={false}>
        <Tooltip permanent direction="top" offset={[0, -10]}>출발지</Tooltip>
      </Marker>
      {Object.entries(targets).filter(([, t]) => validPoint(t)).map(([key, t], i) => (
        <Marker key={key} position={[Number(t.lat), Number(t.lng)]} icon={pinIcon(TEAM_COLOR[USER_TEAM[key]], i + 1)} interactive={false} />
      ))}
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
      const keys = Object.keys(targets);
      setTargets((cur) => {
        const next = { ...cur };
        draft.targets.forEach((t) => {
          const key = keys[t.team - 1];          // 제대 번호대로 채운다 (건너뛴 제대는 그대로 둔다)
          if (key) next[key] = { ...cur[key], lat: String(t.lat), lng: String(t.lon), recon: String(t.recon_min) };
        });
        return next;
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
  const update = (key, field, value) => setTargets((current) => ({ ...current, [key]: { ...current[key], [field]: value } }));
  return (
    <main className="app">
      <header className="top">
        <Brand sub="임무 계획 · 목표를 입력하고 시뮬레이션을 실행합니다" />
        <div className="top-right"><span className="chip">{account.label} · {account.username}</span><button className="icon-btn" onClick={onLogout} aria-label="로그아웃"><LogoutIcon /></button></div>
      </header>
      <div className="body two">
        <section className="stage">
          <div className="map-fill"><InputMap targets={targets} /></div>
          <div className="map-legend-pos"><RiskLegend /></div>
          <div className="tip">입력한 좌표가 번호 핀으로 표시됩니다. 배경은 시작 시각의 위험도입니다.</div>
        </section>
        <aside className="side">
          <MissionTextBox targets={targets} setTargets={setTargets} />
          <section>
            <h2 className="h">정찰 목표</h2>
            <div className="card">
              {Object.entries(targets).map(([key, t], i) => (
                <div className="tgt" key={key}>
                  <span className="no" style={{ background: TEAM_COLOR[USER_TEAM[key]] }}>{i + 1}</span>
                  <label className="f"><small>위도</small><input value={t.lat} onChange={(e) => update(key, "lat", e.target.value)} inputMode="decimal" aria-label={`${t.title} 위도`} /></label>
                  <label className="f"><small>경도</small><input value={t.lng} onChange={(e) => update(key, "lng", e.target.value)} inputMode="decimal" aria-label={`${t.title} 경도`} /></label>
                  <label className="f"><small>정찰(분)</small><input value={t.recon} onChange={(e) => update(key, "recon", e.target.value)} inputMode="numeric" aria-label={`${t.title} 정찰 시간`} /></label>
                </div>
              ))}
            </div>
          </section>
          <p className="hint nomargin">실행하면 균형·정밀·신속 3가지 모드를 같은 조건으로 한 번씩 시뮬레이션합니다. 목표는 작전 구역(그단스크 인근) 안이어야 합니다.</p>
          <button className="btn primary block big" onClick={onSubmit}>시뮬레이션 실행</button>
        </aside>
      </div>
    </main>
  );
}

// 지휘관이 입력한 목표로 임무를 만들고 3개 모드의 시뮬레이션을 서버에서 실행한다 (실제 진행을 보여준다)
function LaunchPage({ targets, onDone, onBack }) {
  const [status, setStatus] = useState("임무를 만드는 중…");
  const [pct, setPct] = useState(0);
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
        const parsed = Object.values(targets).map((t) => ({
          lat: Number(t.lat), lon: Number(t.lng), patrolSec: Math.max(0, Number(t.recon || 0)) * 60,
        }));
        if (parsed.some((t) => !Number.isFinite(t.lat) || !Number.isFinite(t.lon) || t.lat === 0 || t.lon === 0)) {
          throw new Error("세 목표의 위도와 경도를 모두 숫자로 입력하세요.");
        }
        await launchMission({ targets: parsed });
        const set = await waitForRuns((s) => {
          if (!mounted.current) return;
          const done = s.runs.filter((r) => r.status === "COMPLETED").length;
          const avg = Math.round(s.runs.reduce((n, r) => n + r.progress_pct, 0) / Math.max(1, s.runs.length));
          setStatus(`시뮬레이션 실행 중 · 모드 ${done}/${s.runs.length} 완료`);
          setPct(avg);
        });
        if (mounted.current) onDone(set);
      } catch (e) {
        if (mounted.current) setError(e.message);
      }
    })();
    // 의도적으로 한 번만 실행한다 (targets/onDone 이 바뀌어도 임무를 다시 만들지 않는다)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          <h1>{status}</h1>
          <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${Math.max(4, pct)}%` }} /></div>
          <p className="hint">진행 {pct}% · 균형·정밀·신속 3가지 모드를 계산합니다.</p>
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

function LtwrPanel() {
  return <div className="ltwr-scroll">{ltwrMaps.map((map) => <section className="ltwr-card" key={map.file}><h3>{map.title}</h3><iframe src={map.file} title={map.title} /></section>)}</div>;
}

function remainingLabel(turns, turn) {
  const min = Math.max(0, (turns - turn - 1) * 10);
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}:00`;
}

function Seg({ value, options, onChange, disabled }) {
  return (
    <div className="seg">
      {options.map(([key, label]) => (
        <button key={key} className={value === key ? "on" : ""} onClick={() => onChange(key)} disabled={disabled}>{label}</button>
      ))}
    </div>
  );
}

function MainDashboard({ account, onLogout }) {
  const [source, setSource] = useState("server");
  const replay = useReplay(source);
  const [tab, setTab] = useState("events");
  const [notice, setNotice] = useState("");
  const notify = (text) => { setNotice(text); setTimeout(() => setNotice(""), 2400); };

  // 통제관은 자기 제대만, 지휘관은 전체를 본다
  const myTeam = account.role === "commander" ? null : USER_TEAM[account.username];
  const allowedTeams = myTeam ? [myTeam] : null;
  const { model, models, scenario } = replay;
  const turn = model ? model.frames[replay.frame].turn : 0;
  const redByTeam = useMemo(() => (model ? teamRedRatio(model) : {}), [model]);
  const shownTeams = TEAM_ORDER.filter((t) => model?.kpi.per_team[t] && (!allowedTeams || allowedTeams.includes(t)));
  const modeKpi = useMemo(
    () => (models ? Object.fromEntries(Object.entries(models).map(([k, m]) => [k, scopedKpi(m, myTeam)])) : {}),
    [models, myTeam],
  );
  const tabs = [["events", "이벤트"], ["units", "UGV"], ["pareto", "최적화"], ["ltwr", "예보"], ["ai", "AI 어시스턴트"]];

  return (
    <main className="app">
      {notice && <div className="toast" role="status">{notice}</div>}
      <header className="top">
        <Brand />
        <span className="chip"><i className="dot" style={{ background: GRADE_COLOR.G }} />{scenario ? scenario.case : "불러오는 중"}</span>
        <div className="top-right">
          <div className="remaining"><small>남은 시간</small><span className="num">{model ? remainingLabel(model.kpi.turns, turn) : "--:--:--"}</span></div>
          <span className="chip">{account.label} · {account.username}</span>
          <button className="icon-btn" onClick={onLogout} aria-label="로그아웃"><LogoutIcon /></button>
        </div>
      </header>

      <div className="body three">
        <aside className="rail">
          <section>
            <h2 className="h">임무 모드</h2>
            {MODES.map((m) => {
              const k = modeKpi[m.key];
              return (
                <button key={m.key} className={`mode ${replay.mode === m.key ? "on" : ""}`} onClick={() => replay.setMode(m.key)} disabled={!model}>
                  <span className="n">{m.label}{replay.mode === m.key && <small>선택됨</small>}</span>
                  <span className="d">{m.desc}</span>
                  {k && <span className="m"><span>도착 <b className="num">{k.arrived}/{k.total}</b></span><span>SOS <b className="num">{k.sos}</b></span></span>}
                </button>
              );
            })}
          </section>
          <section>
            <h2 className="h">지도 표시</h2>
            <Seg value={replay.overlay} options={Object.entries(OVERLAY_LABEL)} onChange={replay.setOverlay} />
          </section>
          <section>
            <h2 className="h">데이터 출처</h2>
            <Seg value={source} options={Object.entries(REPLAY_SOURCES).map(([k, s]) => [k, s.label])} onChange={setSource} />
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
                      <span title="도착률"><b style={{ width: `${Math.round((pt.arrived / pt.ugv) * 100)}%`, background: TEAM_COLOR[t] }} /></span>
                      <span title="고위험 구간 비율"><b style={{ width: `${Math.round((redByTeam[t] ?? 0) * 100)}%`, background: "var(--risk-r)" }} /></span>
                    </span>
                    <small>{pt.poi ? `POI-${pt.poi}` : "-"} · {pt.arrive_turn == null ? "미도착" : `도착 ${elapsedLabel(pt.arrive_turn + 1)}`}</small>
                  </Tag>
                );
              })}
              <p className="hint tight">막대: 위 도착률(제대 색) · 아래 상대 고위험 구간 비율(빨강)</p>
            </section>
          )}
          {account.role === "commander" && <button className="btn primary block big push" onClick={() => notify("임무를 통제관에게 하달했습니다.")}>임무 하달</button>}
        </aside>

        <div className="center">
          <section className="stage">
            {replay.error && <p className="status error">{replay.error}</p>}
            {replay.loading && <p className="status">재생 데이터를 불러오는 중…</p>}
            {model && (
              <>
                <div className="map-fill replay-map"><ReplayMap replay={replay} allowedTeams={allowedTeams} /></div>
                <div className="map-legend-pos"><RiskLegend /></div>
                <div className="turn"><small>경과</small><b className="num">{elapsedLabel(turn)}</b><small className="num">턴 {turn + 1} / {model.kpi.turns}</small></div>
                <ReplayControls replay={replay} allowedTeams={allowedTeams} />
              </>
            )}
          </section>
          {model && <TeamTimeline replay={replay} allowedTeams={allowedTeams} />}
        </div>

        <aside className="right">
          {model ? <KpiSummary replay={replay} team={myTeam} compact={tab === "ai"} /> : <section className="kpis"><p className="kpis-basis">임무 요약</p></section>}
          <div className="tabs" role="tablist">
            {tabs.map(([key, label]) => (
              <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}>{label}</button>
            ))}
          </div>
          <div className="panel">
            {model && tab === "events" && <EventList replay={replay} allowedTeams={allowedTeams} />}
            {model && tab === "units" && <AgentTable replay={replay} allowedTeams={allowedTeams} />}
            {tab === "pareto" && <ParetoPanel onPickMode={replay.setMode} />}
            {tab === "ltwr" && <LtwrPanel />}
            {tab === "ai" && <AssistantPanel role={account.role} mode={replay.mode} />}
          </div>
        </aside>
      </div>
    </main>
  );
}

// ── 통제관 브리핑 ────────────────────────────────────────────────────────

function UserMissionPage({ account, onConfirm, onLogout }) {
  // 서버가 돌려준 이 제대의 시뮬레이션 결과(균형 모드)를 보여준다. 통제관은 자기 제대 기록만 받는다.
  const replay = useReplay("server");
  const team = USER_TEAM[account.username];
  const unit = units.find((item) => item.key === account.username);
  const model = replay.models?.balance;
  const pt = model?.kpi.per_team[team];
  const poi = pt?.poi ? replay.scenario?.pois.find((p) => p.id === pt.poi) : null;
  const dash = (v) => (v === null || v === undefined ? "-" : v);
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
        <div className="brief-cols">
          <section className="card"><h2 className="h">{account.unit} 자산 현황</h2>
            <p className="kv"><span>통제관 수</span><b className="num">1</b></p>
            <p className="kv"><span>운용 UGV 수</span><b className="num">{dash(pt?.ugv)}</b></p>
            <p className="kv"><span>목표 위도</span><b className="num">{dash(poi?.lat)}</b></p>
            <p className="kv"><span>목표 경도</span><b className="num">{dash(poi?.lon)}</b></p>
          </section>
          <section className="card"><h2 className="h">시뮬레이션 결과 · 균형 (1회 실행)</h2>
            <p className="kv"><span>도착 UGV</span><b className="num">{pt ? `${pt.arrived} / ${pt.ugv}` : "-"}</b></p>
            <p className="kv"><span>SOS 발생</span><b className="num risk">{pt ? `${pt.sos}건` : "-"}</b></p>
            <p className="kv"><span>평균 개입 대기</span><b className="num">{pt ? `${Math.round(pt.wait_turns_mean * 10)}분` : "-"}</b></p>
          </section>
          <section className="card"><h2 className="h">임무 정보</h2>
            <p className="kv"><span>임무 모드</span><b className="amber">균형</b></p>
            <p className="kv"><span>출발 예정 시각</span><b className="num">T+0분</b></p>
            <p className="kv"><span>도착 예정 시각</span><b className="num">{pt ? (pt.arrive_turn == null ? "미도착" : elapsedLabel(pt.arrive_turn + 1)) : "-"}</b></p>
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
