import { useEffect, useMemo, useState } from "react";
import L from "leaflet";
import { ImageOverlay, MapContainer, Marker, TileLayer, Tooltip } from "react-leaflet";
import { accounts, initialTargets, ltwrMaps, units } from "./data";
import { useReplay } from "./replay/useReplay";
import ReplayMap from "./replay/ReplayMap";
import ReplayControls from "./replay/ReplayControls";
import { AgentTable, EventList, KpiSummary } from "./replay/SidePanels";
import { REPLAY_SOURCES, TEAM_COLOR, TEAM_UNIT, USER_TEAM, elapsedLabel, teamRedRatio } from "./replay/replayModel";

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";
const MAP_BOUNDS = [[54.2977, 18.2640], [54.5209, 18.6479]];

function markerIcon(color) {
  return L.divIcon({
    html: `<div class="leaflet-marker-dot" style="background:${color}"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    className: "leaflet-marker-wrapper",
  });
}

function LoginPage({ onLogin }) {
  const [opened, setOpened] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function submit(event) {
    event?.preventDefault();
    const account = accounts[username.trim()];
    if (!account || account.password !== password) return setError("정보가 올바르지 않습니다.");
    onLogin({ ...account, username: username.trim() }, setError);
  }

  return (
    <main className="login-page">
      <img src="/loginpage_picture_4.png" className="login-background" alt="UGV Tactical Decision Support" />
      {!opened && <><button className="splash-button" onClick={() => setOpened(true)} aria-label="로그인 열기" /><p className="splash-hint">Click to continue...</p></>}
      {opened && (
        <div className="login-overlay">
          <form className="login-card" onSubmit={submit}>
            <div className="login-title"><strong>UGV</strong><span>Tactical Decision Support</span></div>
            <label>USER ID<input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus /></label>
            <label>PASSWORD<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
            {error && <p className="login-error">{error}</p>}
            <button className="login-submit">Login to Dashboard</button>
          </form>
        </div>
      )}
    </main>
  );
}

function InputMap({ targets, visible }) {
  const markerColors = { user1: "#3b82f6", user2: "#52c41a", user3: "#a855f7" };
  const visibleMarkers = Object.entries(targets).filter(([key, target]) => (
    visible[key] && Number.isFinite(Number(target.lat)) && Number.isFinite(Number(target.lng))
  ));

  return (
    <div className="input-map">
      <MapContainer bounds={MAP_BOUNDS} boundsOptions={{ padding: [8, 8] }} zoomControl attributionControl={false}>
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={18}
          opacity={0.5}
        />
        <ImageOverlay url={`${API_URL}/api/map/tactical/terrain-image`} bounds={MAP_BOUNDS} opacity={0.7} />
        <ImageOverlay url={`${API_URL}/api/map/tactical/buffer-image`} bounds={MAP_BOUNDS} opacity={0.5} />
        <ImageOverlay url={`${API_URL}/api/map/tactical/cost-image?layer=risk`} bounds={MAP_BOUNDS} opacity={0.78} />
        <Marker position={[54.48, 18.32]} icon={markerIcon("#e67e22")}>
          <Tooltip permanent direction="top" offset={[0, -12]}>출발지</Tooltip>
        </Marker>
        {visibleMarkers.map(([key, target]) => (
          <Marker key={key} position={[Number(target.lat), Number(target.lng)]} icon={markerIcon(markerColors[key])}>
            <Tooltip permanent direction="top" offset={[0, -12]}>{target.title}</Tooltip>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}

function CommanderInputPage({ targets, setTargets, onSubmit }) {
  const [visible, setVisible] = useState({});
  const update = (key, field, value) => setTargets((current) => ({ ...current, [key]: { ...current[key], [field]: value } }));
  return (
    <main className="input-root">
      <div className="input-shell">
        <section className="input-map-panel">
          <h1>작전 지역</h1><p>지형 지도에서 제대별 도착지를 확인하세요.</p>
          <InputMap targets={targets} visible={visible} />
        </section>
        <aside className="input-side-panel">
          {Object.entries(targets).map(([key, target]) => (
            <section className="destination-card" key={key}>
              <h2>{target.title} 입력</h2>
              <div className="field-row"><label>위도</label><input value={target.lat} onChange={(e) => update(key, "lat", e.target.value)} /></div>
              <div className="field-row"><label>경도</label><input value={target.lng} onChange={(e) => update(key, "lng", e.target.value)} /></div>
              <button onClick={() => setVisible((current) => ({ ...current, [key]: true }))}>{target.title} 표시</button>
            </section>
          ))}
          <button className="simulation-button" onClick={onSubmit}>시뮬레이션 실행</button>
        </aside>
      </div>
    </main>
  );
}

function LoadingPage({ onDone }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 2000);
    return () => clearTimeout(timer);
  }, [onDone]);
  return <main className="loading-page"><div className="sticks">{[0,1,2,3,4,5].map((n) => <i key={n} />)}</div><h1>시뮬레이션 실행 중...</h1></main>;
}

function LineChart({ values, colors }) {
  const pts = values.map((v, i) => `${42 + i * 105},${100 - v * .72}`).join(" ");
  return (
    <svg viewBox="0 0 300 110" className="line-chart">
      {[20,40,60,80,100].map((v) => <line key={v} x1="28" x2="285" y1={100-v*.72} y2={100-v*.72} />)}
      <polyline points={pts} />
      {values.map((v,i) => <g key={i}><circle cx={42+i*105} cy={100-v*.72} r="5" fill={colors[i]} /><text x={42+i*105} y={83-v*.72}>{v}</text><text x={42+i*105} y="105">{i+1}제대</text></g>)}
    </svg>
  );
}

function LtwrPanel() {
  return <div className="ltwr-scroll">{ltwrMaps.map((map) => <section className="ltwr-card" key={map.file}><h3>{map.title}</h3><iframe src={map.file} title={map.title} /></section>)}</div>;
}

function AssetSummary({ role, user }) {
  return (
    <div className="asset-summary">
      <button>부대<br /><b>3</b></button>
      {(role === "commander" ? units : units.filter((u) => u.key === user)).map((unit) => <button key={unit.key}>{unit.name}<br /><b>{unit.key === "user2" ? 5 : 4}</b></button>)}
    </div>
  );
}

const MODE_LABEL_TO_KEY = { 균형: "balance", 정밀: "explore", 신속: "rush" };
const OVERLAY_LABEL = { total: "종합", mobility: "기동성", sensor: "센서" };
const TEAM_ORDER = ["Alpha", "Bravo", "Charlie"];

function remainingLabel(turns, turn) {
  const min = Math.max(0, (turns - turn - 1) * 10);
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}:00`;
}

function MainDashboard({ account, targets, onLogout }) {
  const [source, setSource] = useState("reference");
  const replay = useReplay(source);
  const [tab, setTab] = useState("events");
  const [notice, setNotice] = useState("");
  const notify = (text) => { setNotice(text); setTimeout(() => setNotice(""), 2400); };

  // 통제관은 자기 제대만, 지휘관은 전체를 본다
  const myTeam = account.role === "commander" ? null : USER_TEAM[account.username];
  const allowedTeams = myTeam ? [myTeam] : null;
  const { model, scenario } = replay;
  const turn = model ? model.frames[replay.frame].turn : 0;
  const redByTeam = useMemo(() => (model ? teamRedRatio(model) : {}), [model]);
  const arrivalPct = TEAM_ORDER.map((t) => {
    const pt = model?.kpi.per_team[t];      // 임무에 따라 제대가 3개보다 적을 수 있다
    return pt ? Math.round((pt.arrived / pt.ugv) * 100) : 0;
  });
  const redPct = TEAM_ORDER.map((t) => Math.round((redByTeam[t] ?? 0) * 100));
  const colors = TEAM_ORDER.map((t) => TEAM_COLOR[t]);

  return (
    <main className="dashboard-root">
      {notice && <div className="toast">{notice}</div>}
      <div className="dashboard-shell">
        <header className="top-left">
          <button className="back-button" onClick={onLogout}>⬅</button>
          <div><span>{scenario ? scenario.case : "불러오는 중"}</span><strong>{account.label}</strong></div>
          <div className="remaining"><span>남은시간</span><strong>{model ? remainingLabel(model.kpi.turns, turn) : "--:--:--"}</strong></div>
        </header>
        <section className="unit-table">
          <div className="unit-head"><span></span><span>운용 UGV 수</span><span>도착지 정보</span><span>출발 예정 시각</span><span>도착 예정 시각</span></div>
          {model && TEAM_ORDER.filter((t) => model.kpi.per_team[t] && (!allowedTeams || allowedTeams.includes(t))).map((t) => {
            const pt = model.kpi.per_team[t];
            return (
              <div className="unit-line" key={t}>
                <b>{TEAM_UNIT[t]}</b>
                <i style={{ background: TEAM_COLOR[t] }}>{pt.ugv}</i>
                <span>{pt.poi ? `POI-${pt.poi}` : "-"}</span>
                <span>T+0분</span>
                <span>{pt.arrive_turn == null ? "미도착" : elapsedLabel(pt.arrive_turn + 1)}</span>
              </div>
            );
          })}
        </section>
        <aside className="left-panel">
          <h2>임무 모드</h2>
          <div className="mode-buttons">
            {Object.entries(MODE_LABEL_TO_KEY).map(([label, key]) => (
              <button className={replay.mode === key ? "active" : ""} onClick={() => replay.setMode(key)} disabled={!model} key={key}>{label}</button>
            ))}
          </div>
          <h2>데이터 출처</h2>
          <div className="mode-buttons">
            {Object.entries(REPLAY_SOURCES).map(([key, s]) => (
              <button className={source === key ? "active" : ""} onClick={() => setSource(key)} key={key}>{s.label}</button>
            ))}
          </div>
          <h2>지도 표시</h2>
          <div className="mode-buttons">
            {Object.entries(OVERLAY_LABEL).map(([key, label]) => (
              <button className={replay.overlay === key ? "active" : ""} onClick={() => replay.setOverlay(key)} key={key}>{label}</button>
            ))}
          </div>
          {!myTeam && (
            <>
              <h2>제대 표시</h2>
              <div className="mode-buttons">
                {TEAM_ORDER.map((t) => (
                  <button
                    key={t}
                    className={`team-chip ${replay.teams[t] ? "on" : ""}`}
                    style={{ borderColor: TEAM_COLOR[t] }}
                    onClick={() => replay.toggleTeam(t)}
                  >{TEAM_UNIT[t]}</button>
                ))}
              </div>
            </>
          )}
          <h2>재생</h2>
          <div className="control-buttons">
            <button className={replay.playing ? "active" : ""} onClick={() => !replay.playing && replay.togglePlay()} disabled={!model}>재생</button>
            <button onClick={() => replay.setPlaying(false)} disabled={!model}>정지</button>
          </div>
          <h2>제대별 도착률 (%)</h2><LineChart values={arrivalPct} colors={colors} />
          <h2>제대별 고위험 구간 비율 (%)</h2><LineChart values={redPct} colors={colors} />
          {account.role === "commander" && <button className="delivery-button" onClick={() => notify("임무를 통제관에게 하달했습니다.")}>임무 하달</button>}
        </aside>
        <section className="center-panel">
          {replay.error && <p className="replay-status error">{replay.error}</p>}
          {replay.loading && <p className="replay-status">재생 데이터를 불러오는 중…</p>}
          {model && (
            <div className="replay-stage">
              <div className="replay-map"><ReplayMap replay={replay} allowedTeams={allowedTeams} /></div>
              <ReplayControls replay={replay} />
            </div>
          )}
        </section>
        <aside className="right-panel">
          {model ? <KpiSummary replay={replay} team={myTeam} /> : <section className="mission-summary"><h2>임무 요약</h2></section>}
          <section className="ltwr-panel">
            <div className="tabs">
              {[["events", "이벤트"], ["units", "UGV 상태"], ["ltwr", "LTWR 예측"]].map(([key, label]) => (
                <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
              ))}
            </div>
            {model && tab === "events" && <EventList replay={replay} allowedTeams={allowedTeams} />}
            {model && tab === "units" && <AgentTable replay={replay} allowedTeams={allowedTeams} />}
            {tab === "ltwr" && <><h2>지형작전 기상 위험도 - LTWR</h2><LtwrPanel /></>}
          </section>
        </aside>
      </div>
    </main>
  );
}

function UserMissionPage({ account, targets, onConfirm }) {
  // 대시보드와 같은 재생 데이터(균형 모드)에서 읽는다. 예전에는 화면에 숫자를 직접 적어 두어 대시보드와 서로 달랐다.
  const replay = useReplay("reference");
  const team = USER_TEAM[account.username];
  const unit = units.find((item) => item.key === account.username);
  const model = replay.models?.balance;
  const pt = model?.kpi.per_team[team];
  const allTeams = model ? Object.values(model.kpi.per_team) : [];
  const poi = pt?.poi ? replay.scenario?.pois.find((p) => p.id === pt.poi) : null;
  const dash = (v) => (v === null || v === undefined ? "-" : v);
  return (
    <main className="briefing-root">
      <header><h1>{unit.name} 통제관 임무 브리핑</h1><p>지휘관이 하달한 임무 정보를 확인하세요.</p></header>
      <div className="briefing-cards">
        <section><h2>부대 기본자산</h2><p><span>총 제대 수</span><b>{dash(allTeams.length || null)}</b></p><p><span>총 통제관 수</span><b>{dash(allTeams.length || null)}</b></p><p><span>총 정찰 UGV 수</span><b>{dash(allTeams.reduce((n, t) => n + t.ugv, 0) || null)}</b></p></section>
        <section><h2>{unit.name} 자산 현황</h2><p><span>통제관 수</span><b>1</b></p><p><span>운용 UGV 수</span><b>{dash(pt?.ugv)}</b></p><p><span>목표 위도</span><b>{targets[unit.key].lat || dash(poi?.lat)}</b></p><p><span>목표 경도</span><b>{targets[unit.key].lng || dash(poi?.lon)}</b></p></section>
        <section><h2>임무 정보</h2><p><span>임무 모드</span><b className="highlight">균형</b></p><p><span>운용 UGV 수</span><b className="highlight">{dash(pt?.ugv)}</b></p><p><span>출발 예정 시각</span><b>T+0분</b></p><p><span>도착 예정 시각</span><b>{pt ? (pt.arrive_turn == null ? "미도착" : elapsedLabel(pt.arrive_turn + 1)) : "-"}</b></p></section>
      </div>
      <button className="briefing-button" onClick={onConfirm}>통제관 메인 페이지로 넘어가기</button>
    </main>
  );
}

export default function App() {
  const [account, setAccount] = useState(null);
  const [page, setPage] = useState("login");
  const [targets, setTargets] = useState(initialTargets);
  const [commanderReady, setCommanderReady] = useState(false);

  function login(next, setError) {
    if (next.role === "controller" && !commanderReady) return setError("아직 지휘관이 임무 입력 및 시뮬레이션을 완료하지 않았습니다.");
    setAccount(next);
    setPage(next.role === "commander" ? "input" : "briefing");
  }
  function logout() { setAccount(null); setPage("login"); }
  if (!account || page === "login") return <LoginPage onLogin={login} />;
  if (page === "input") return <CommanderInputPage targets={targets} setTargets={setTargets} onSubmit={() => setPage("loading")} />;
  if (page === "loading") return <LoadingPage onDone={() => { setCommanderReady(true); setPage("main"); }} />;
  if (page === "briefing") return <UserMissionPage account={account} targets={targets} onConfirm={() => setPage("main")} />;
  return <MainDashboard account={account} targets={targets} onLogout={logout} />;
}
