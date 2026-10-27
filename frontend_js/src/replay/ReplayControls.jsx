import { elapsedLabel } from "./replayModel";

const SPEEDS = [1, 2, 4, 8];

// 지도 밖 하단 재생 막대: 재생/정지, 배속, 시간 슬라이더
export default function ReplayControls({ replay }) {
  const { model, frame, lastFrame, seek, playing, togglePlay, speed, setSpeed } = replay;
  const f = model.frames[frame];
  return (
    <div className="replay-bar">
      <button className="replay-play" onClick={togglePlay} aria-label={playing ? "정지" : "재생"}>
        {playing ? "⏸" : "▶"}
      </button>
      <input
        type="range" min={0} max={lastFrame} value={frame}
        onChange={(e) => seek(Number(e.target.value))}
        aria-label="시간"
      />
      <span className="replay-time">턴 {f.turn + 1}/{model.kpi.turns} · {elapsedLabel(f.turn)}</span>
      <div className="replay-speed">
        {SPEEDS.map((s) => (
          <button key={s} className={speed === s ? "active" : ""} onClick={() => setSpeed(s)}>{s}x</button>
        ))}
      </div>
    </div>
  );
}
