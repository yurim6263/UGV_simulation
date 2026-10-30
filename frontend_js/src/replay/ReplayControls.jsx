import { elapsedLabel } from "./replayModel";

const SPEEDS = [1, 2, 4, 8];

// 지도 아래에 떠 있는 재생 막대: 재생/정지, 시간 슬라이더(SOS 발생 시점 표시), 배속
export default function ReplayControls({ replay, allowedTeams }) {
  const { model, frame, lastFrame, seek, playing, togglePlay, speed, setSpeed, teams } = replay;
  const f = model.frames[frame];
  const sos = model.events.filter((e) => e.type === "sos" && teams[e.team] && (!allowedTeams || allowedTeams.includes(e.team)));
  return (
    <div className="dock">
      <button className="dock-play" onClick={togglePlay} aria-label={playing ? "정지" : "재생"}>
        {playing
          ? <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="currentColor" /></svg>
          : <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z" fill="currentColor" /></svg>}
      </button>
      <span className="dock-time">{elapsedLabel(f.turn)}</span>
      <div className="dock-track">
        <input
          type="range" min={0} max={lastFrame} value={frame}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label="시간"
        />
        {sos.map((e, i) => (
          <span key={i} className="dock-tick" title={e.text} style={{ left: `calc(8px + (100% - 16px) * ${e.frame / Math.max(1, lastFrame)})` }} />
        ))}
      </div>
      <span className="dock-turn">턴 {f.turn + 1} / {model.kpi.turns}</span>
      <div className="dock-speed">
        {SPEEDS.map((s) => (
          <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>
        ))}
      </div>
    </div>
  );
}
