import { useMemo } from "react";
import {
  GRADE_COLOR, KPI_ROWS, TEAM_COLOR, TEAM_UNIT, actionLabel, agentLabel, elapsedLabel, scopedKpi, stateAt,
} from "./replayModel";

// 임무 요약: 선택한 모드의 KPI 카드 + 다른 모드와 한눈에 비교
export function KpiSummary({ replay, team }) {
  const { models, mode, scenario } = replay;
  const all = useMemo(
    () => Object.fromEntries(Object.entries(models).map(([key, m]) => [key, scopedKpi(m, team)])),
    [models, team],
  );
  const cur = all[mode];
  return (
    <section className="kpis">
      <p className="kpis-basis">{team ? TEAM_UNIT[team] : "전체"} · 시뮬레이션 1회 기록 기준</p>
      {KPI_ROWS.map(([label, get, unit, hint], i) => (
        <div className={`kpi ${label.startsWith("SOS") ? "alert" : ""} ${i === KPI_ROWS.length - 1 ? "wide" : ""}`} key={label} title={hint}>
          <small>{label}{hint && <span className="hint-mark" aria-hidden="true"> ⓘ</span>}</small>
          <b>{get(cur)}<u>{unit}</u></b>
          <em>
            {scenario.modes.map((m) => (
              <i key={m.key} className={m.key === mode ? "on" : ""}>{m.label} {get(all[m.key])}</i>
            ))}
          </em>
        </div>
      ))}
      <p className="kpis-note">상대 고위험 구간은 순위로 나눈 등급(날씨 강도와 무관), 평균 위험도는 0~1 절대값입니다.</p>
    </section>
  );
}

// 이벤트 타임라인: 항목을 누르면 그 시점으로 이동
export function EventList({ replay, allowedTeams }) {
  const { model, frame, seek, teams, setSelected } = replay;
  const shown = model.events.filter((e) => teams[e.team] && (!allowedTeams || allowedTeams.includes(e.team)));
  return (
    <div className="event-list">
      {shown.length === 0 && <p className="empty">표시할 이벤트가 없습니다.</p>}
      {shown.map((e, i) => (
        <button
          key={i}
          className={`event ${e.type} ${e.frame <= frame ? "past" : ""}`}
          onClick={() => { seek(e.frame); setSelected(model.agents[e.agent].id); }}
        >
          <span className="when">{elapsedLabel(e.turn)}</span>
          <span className="what">{e.text}</span>
        </button>
      ))}
    </div>
  );
}

// UGV 상태표 + 선택한 UGV 의 타일 기상 정보
export function AgentTable({ replay, allowedTeams }) {
  const { model, frame, teams, selected, setSelected } = replay;
  const rows = model.agents
    .map((agent, i) => ({ agent, s: stateAt(model, frame, i) }))
    .filter(({ agent }) => agent.kind !== "OP" && teams[agent.team] && (!allowedTeams || allowedTeams.includes(agent.team)));
  const sel = rows.find((r) => r.agent.id === selected);
  const fmt = (v, d = 3) => (v == null ? "NA" : Number(v).toFixed(d));
  return (
    <div className="agent-table">
      <table>
        <tbody>
          {rows.map(({ agent, s }) => (
            <tr key={agent.id} className={agent.id === selected ? "sel" : ""} onClick={() => setSelected(agent.id)}>
              <td><i style={{ background: TEAM_COLOR[agent.team] }} /></td>
              <td>{agentLabel(agent)}</td>
              <td>{s ? actionLabel(s.action) : "출발 전"}</td>
              <td>{s && <i className="grade" style={{ background: GRADE_COLOR[s.grade] }}>{s.grade}</i>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sel?.s && (
        <dl className="tile-info">
          <dt>선택</dt><dd>{agentLabel(sel.agent)}</dd>
          <dt>종합 위험</dt><dd>{fmt(sel.s.total)}</dd>
          <dt>기동 위험</dt><dd>{fmt(sel.s.mob)}</dd>
          <dt>센서 위험</dt><dd>{fmt(sel.s.sen)}</dd>
          <dt>강수(mm/h)</dt><dd>{fmt(sel.s.rain)}</dd>
          <dt>토양수분</dt><dd>{fmt(sel.s.swvl1)}</dd>
          <dt>적설(m)</dt><dd>{fmt(sel.s.sde, 4)}</dd>
          <dt>안개 확률</dt><dd>{fmt(sel.s.fog)}</dd>
          <dt>잔여 AP</dt><dd>{sel.s.ap.toLocaleString()}</dd>
        </dl>
      )}
    </div>
  );
}
