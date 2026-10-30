import { useMemo } from "react";
import { GRADE_COLOR, TEAM_COLOR, TEAM_UNIT, elapsedLabel, teamTimeline } from "./replayModel";

const TEAM_ORDER = ["Alpha", "Bravo", "Charlie"];

// 제대별 타임라인: 한 칸 = 10분(한 턴). 칸 색 = 그 턴에 UGV 가 있던 곳의 가장 나쁜 위험 등급.
// 칸을 누르면 그 시점으로 이동한다. SOS(빨간 마름모)·운용자 개입(흰 점)이 시간순으로 보인다.
export default function TeamTimeline({ replay, allowedTeams }) {
  const { model, frame, seek, teams, setSelected } = replay;
  const lanes = useMemo(
    () => TEAM_ORDER.filter((t) => model.kpi.per_team[t] && (!allowedTeams || allowedTeams.includes(t)) && teams[t])
      .map((t) => ({ team: t, ...teamTimeline(model, t) })),
    [model, allowedTeams, teams],
  );
  const firstFrame = useMemo(() => {
    const map = new Map();
    model.frames.forEach((f, i) => { if (!map.has(f.turn)) map.set(f.turn, i); });
    return map;
  }, [model]);
  const turns = model.kpi.turns;
  const cur = model.frames[frame].turn;
  const pct = (turn) => `${((turn + 0.5) / turns) * 100}%`;
  const ticks = Array.from({ length: Math.ceil(turns / 3) }, (_, i) => i * 3).filter((t) => t < turns);

  return (
    <section className="timeline" aria-label="제대별 타임라인">
      <div className="tl-head">
        <b>제대별 타임라인 · 한 칸 10분</b>
        <span className="tl-legend">
          {Object.entries(GRADE_COLOR).map(([g, c]) => <span key={g}><i style={{ background: c }} />{g}</span>)}
          <span><i className="diamond" />SOS</span>
          <span><i className="dotw" />운용자 개입</span>
          <span><i className="done" />도착 후</span>
        </span>
      </div>
      {lanes.length === 0 && <p className="empty">표시할 제대가 없습니다.</p>}
      <div className="tl-body">
      {lanes.map((lane) => (
        <div className="tl-lane" key={lane.team}>
          <div className="tl-name"><i style={{ background: TEAM_COLOR[lane.team] }} />{TEAM_UNIT[lane.team]}</div>
          <div className="tl-cells">
            {lane.cells.map((c) => (
              <button
                key={c.turn}
                className={`tl-cell ${c.done ? "done" : ""}`}
                style={c.grade && !c.done ? { background: GRADE_COLOR[c.grade] } : undefined}
                title={`${elapsedLabel(c.turn)} · ${c.done ? "도착 후" : c.grade ? `위험 등급 ${c.grade}` : "기록 없음"}`}
                aria-label={`${TEAM_UNIT[lane.team]} ${elapsedLabel(c.turn)}`}
                onClick={() => seek(firstFrame.get(c.turn) ?? 0)}
              />
            ))}
            {lane.events.filter((e) => e.type === "sos").map((e, i) => (
              <button key={`s${i}`} className="tl-sos" style={{ left: pct(e.turn) }} title={e.text}
                aria-label={e.text} onClick={() => { seek(e.frame); setSelected(null); }} />
            ))}
            {lane.events.filter((e) => e.type === "intervene").map((e, i) => (
              <button key={`i${i}`} className="tl-iv" style={{ left: pct(e.turn) }} title={e.text}
                aria-label={e.text} onClick={() => seek(e.frame)} />
            ))}
          </div>
        </div>
      ))}
      <div className="tl-lane axis">
        <div className="tl-name" />
        <div className="tl-axis">
          {ticks.map((t) => <span key={t} style={{ left: pct(t) }}>{t * 10}</span>)}
        </div>
      </div>
      <i className="tl-cursor" style={{ left: `calc(88px + (100% - 88px) * ${(cur + 0.5) / turns})` }} />
      </div>
    </section>
  );
}
