import { useEffect, useMemo, useState } from "react";
import { getPlan } from "../api";

// 편성 탭: 목표 위치에 맞게 계산한 "제대별 UGV 투입 대수(1~3대)" 후보 전체와 모드별 추천을 보여 준다.
// 숫자는 시뮬레이션 추정이다 (시드 몇 개의 평균). 작은 차이는 우연일 수 있다.
const MODES = [["balance", "균형"], ["explore", "정밀"], ["rush", "신속"]];
const key = (f) => f.join("-");

export default function FormationPanel({ replay }) {
  const missionId = replay.scenario?.mission_id;
  const [state, setState] = useState({ loading: true });
  const [sort, setSort] = useState({ by: "v1", dir: -1 });
  const [onlyBest, setOnlyBest] = useState(false);

  useEffect(() => {
    if (!missionId) { setState({ none: true }); return undefined; }
    let cancelled = false;
    getPlan(missionId)
      .then((p) => { if (!cancelled) setState(p.status === "COMPLETED" ? { plan: p.plan, cached: p.cached } : { none: true }); })
      .catch(() => { if (!cancelled) setState({ none: true }); });
    return () => { cancelled = true; };
  }, [missionId]);

  const mode = MODES.some(([k]) => k === replay.mode) ? replay.mode : "balance";   // "지정 편성" 보기일 때는 균형 표를 보여 준다
  const plan = state.plan;
  const rows = useMemo(() => {
    const cands = plan?.modes[mode]?.candidates ?? [];
    const list = onlyBest ? cands.filter((c) => c.pareto) : cands;
    return [...list].sort((a, b) => (a[sort.by] - b[sort.by]) * sort.dir || a.total - b.total);
  }, [plan, mode, sort, onlyBest]);

  if (state.loading) return <p className="empty">불러오는 중…</p>;
  if (state.none) return <p className="empty">이 임무는 편성 계산 없이 실행되어, 보유 UGV를 제대에 고르게(제대당 최대 3대) 나눴습니다.</p>;

  const picks = Object.fromEntries(MODES.map(([k]) => [k, plan.modes[k].pick]));
  const labelsOf = (formation) => MODES.filter(([k]) => key(picks[k].formation) === key(formation)).map(([, l]) => l);
  const head = (by, label) => (
    <th><button className={sort.by === by ? "on" : ""} onClick={() => setSort((s) => ({ by, dir: s.by === by ? -s.dir : by === "v1" || by === "arrival" ? -1 : 1 }))}>{label}{sort.by === by ? (sort.dir < 0 ? " ▼" : " ▲") : ""}</button></th>
  );

  return (
    <div className="formation">
      <p className="fm-intro">
        <b>제대마다 UGV를 몇 대 보낼까?</b> 목표 위치(기상·거리 반영)에서 제대당 1~3대의 모든 조합을 시뮬레이션으로 시험해, 모드마다 우선순위에 맞는 편성을 골랐습니다.
        보유 9대 중 일부만 투입할 수 있습니다.
      </p>
      <div className="fm-picks">
        {MODES.map(([k, label]) => {
          const p = picks[k];
          return (
            <button key={k} className={mode === k ? "on" : ""} onClick={() => replay.setMode(k)}>
              <small>{label}</small>
              <b>{key(p.formation)}</b>
              <span>{p.total}대 투입</span>
            </button>
          );
        })}
      </div>
      <p className="fm-reason">{picks[mode].reason}{!picks[mode].constraint_met && " (제약 불충족)"}</p>
      {new Set(MODES.map(([k]) => key(picks[k].formation))).size === 1 && <p className="hint tight">이 목표에서는 세 모드의 편성이 같습니다. 쉬운 임무라 UGV를 늘려도 얻는 것이 없거나, 도착 기준을 맞추는 편성이 하나뿐이기 때문입니다.</p>}
      <label className="fm-filter"><input type="checkbox" checked={onlyBest} onChange={(e) => setOnlyBest(e.target.checked)} /> 다른 편성에 모든 면에서 밀리지 않는 후보만 (▲ 표시)</label>
      <div className="fm-table">
        <table>
          <thead><tr><th>편성</th>{head("total", "대")}{head("arrival", "도착")}{head("v1", "수색")}{head("v2", "시간")}{head("v3", "부하")}</tr></thead>
          <tbody>
            {rows.map((c) => {
              const labels = labelsOf(c.formation);
              const mine = key(c.formation) === key(picks[mode].formation);
              return (
                <tr key={key(c.formation)} className={mine ? "pick" : ""} title={`SOS 평균 ${c.sos}건 · 수색 ±${(c.v1_sd * 100).toFixed(1)}%p · 시간 ±${c.v2_sd}분 (시드 ${c.seeds}개)`}>
                  <td>{key(c.formation)}{c.pareto && <i className="par" aria-label="밀리지 않는 후보">▲</i>}{labels.length > 0 && <em>{labels.join("·")}</em>}</td>
                  <td>{c.total}</td>
                  <td className={c.arrival < plan.min_arrival ? "bad" : ""}>{Math.round(c.arrival * 100)}%</td>
                  <td>{(c.v1 * 100).toFixed(1)}%</td>
                  <td>{Math.round(c.v2)}분</td>
                  <td>{Math.round(c.v3)}분</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="hint tight">
        도착: UGV 중 도착한 비율(빨강은 제약 {Math.round(plan.min_arrival * 100)}% 미달). 수색: 센서로 훑은 면적. 시간: 작전 시간. 부하: 운용자 대기열이 밀린 시간.
        시드 {plan.seeds.length}개의 평균이라 작은 차이는 우연일 수 있습니다 (행에 마우스를 올리면 편차). 시험 {plan.episodes}회{state.cached ? ", 저장된 계산 결과를 사용" : `, ${plan.elapsed_sec}초`}.
      </p>
    </div>
  );
}
