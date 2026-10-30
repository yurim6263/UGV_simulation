import { useEffect, useState } from "react";
import { TEAM_UNIT } from "./replayModel";

// NSGA-II 최적화 결과: 파레토 곡선(수색 면적 x 작전 시간) + 탈락한 개체의 분포 + 전술 메뉴판(신속/정밀/균형).
// 데이터: static/optimization/pareto.json (backend/scripts/run_nsga2.py 가 만든 결과의 사본)
const MODES = [
  { key: "rush", label: "신속", color: "#7dd3fc" },
  { key: "balance", label: "균형", color: "#e6edf3" },
  { key: "explore", label: "정밀", color: "#c4b5fd" },
];
const W = 300;
const H = 190;
const PAD = { l: 38, r: 8, t: 8, b: 28 };

const pm = (v, ci, digits = 0, unit = "") => `${v.toFixed(digits)}${unit}${ci ? ` ±${ci.toFixed(digits)}` : ""}`;

function scaler(values, lo, hi) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return (v) => lo + ((v - min) / span) * (hi - lo);
}

export default function ParetoPanel({ onPickMode }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}optimization/pareto.json`)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(setData)
      .catch(() => setError("최적화 결과가 없습니다. backend/scripts/run_nsga2.py 를 실행하세요."));
  }, []);

  if (error) return <p className="empty">{error}</p>;
  if (!data) return <p className="empty">불러오는 중…</p>;

  const cloud = data.archive;
  // 차트는 모두 '최적화 때의 평가값'으로 그린다 (개체 구름과 같은 기준). 검증 값은 아래 전술 메뉴판의 숫자로만 보여준다.
  const front = data.front.filter((f) => f.train);
  const xs = [...cloud.map((c) => c.v2), ...front.map((f) => f.train.v2)];
  const ys = [...cloud.map((c) => c.v1), ...front.map((f) => f.train.v1)];
  const sx = scaler(xs, PAD.l, W - PAD.r);
  const sy = scaler(ys, H - PAD.b, PAD.t);          // 위쪽이 수색 면적이 큰 쪽
  const picked = Object.entries(data.archetypes).map(([mode, idx]) => ({ mode, idx, f: data.front[idx] }));
  const refs = data.references ?? {};
  const blind = refs.weather_blind;
  const best = data.front[data.archetypes.balance]?.validation;

  return (
    <div className="pareto">
      <p className="pareto-intro">
        <b>이 탭은 무엇인가요?</b> 편성(제대별 UGV 수)과 전술 설정을 컴퓨터가 수백 번 시험(NSGA-II 최적화)해서 찾은 결과입니다.
        가로는 작전 시간, 세로는 수색 면적이라 <b>왼쪽 위로 갈수록 좋습니다</b>. 점 하나가 시험한 전술 하나이고, 큰 점이 신속·균형·정밀 대표 전술입니다.
        아래 메뉴판을 누르면 그 모드로 지도가 바뀝니다.
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="pareto-chart" role="img" aria-label="파레토 곡선">
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} />
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={H - PAD.b} />
        {cloud.map((c, i) => (
          <circle key={i} cx={sx(c.v2)} cy={sy(c.v1)} r="2" className={c.feasible ? "cloud" : "cloud bad"} />
        ))}
        {front.map((f, i) => (
          <circle key={i} cx={sx(f.train.v2)} cy={sy(f.train.v1)} r="3.2" className="front" />
        ))}
        {picked.map(({ mode, f }) => {
          const m = MODES.find((x) => x.key === mode);
          return f.train && (
            <g key={mode}>
              <circle cx={sx(f.train.v2)} cy={sy(f.train.v1)} r="6" fill={m.color} stroke="#fff" strokeWidth="1.5" />
              <text x={sx(f.train.v2)} y={sy(f.train.v1) - 9} className="tag" fill={m.color}>{m.label}</text>
            </g>
          );
        })}
        <text x={(PAD.l + W - PAD.r) / 2} y={H - 6} className="axis">작전 시간 (분) →</text>
        <text x="10" y={(PAD.t + H - PAD.b) / 2} className="axis" transform={`rotate(-90 10 ${(PAD.t + H - PAD.b) / 2})`}>수색 면적 ↑</text>
      </svg>
      <p className="legend">
        <i className="dot cloud" /> 평가한 개체 {cloud.length}개 · <i className="dot front" /> 파레토 해 {data.front.length}개 · 큰 점 = 전술 메뉴 (모두 최적화 때의 평가값)
      </p>

      <h3>전술 메뉴판 <small>새 시드 {data.meta.val_seeds.length}개 x 강도 {data.meta.scales.length}개의 몬테카를로 (평균 ± 95% 신뢰구간)</small></h3>
      {MODES.map((m) => {
        const item = data.front[data.archetypes[m.key]];
        if (!item?.validation) return null;
        const v = item.validation;
        return (
          <button key={m.key} className="archetype" style={{ borderLeftColor: m.color }} onClick={() => onPickMode?.(m.key)}>
            <b>{m.label}</b>
            <span>편성 {item.formation.join("-")}</span>
            <span>도착률 {pm(v.arrival * 100, v.arrival_ci95 * 100, 0, "%")} <em>(하위 5%: {(v.arrival_p5 * 100).toFixed(0)}%)</em></span>
            <span>수색 {pm(v.v1 * 100, v.v1_ci95 * 100, 1, "%")} · 시간 {pm(v.v2, v.v2_ci95, 0, "분")} · 과부하 {pm(v.v3, v.v3_ci95, 0, "분")}</span>
          </button>
        );
      })}

      {blind && best && (
        <p className="ab">
          날씨를 무시한 기준선 도착률 <b>{(blind.arrival * 100).toFixed(0)}%</b> → 균형 전술 <b>{(best.arrival * 100).toFixed(0)}%</b>
          {" "}(작전 시간 {blind.v2.toFixed(0)}분 → {best.v2.toFixed(0)}분)
        </p>
      )}
      <p className="note">{data.meta.note} 제약: 평균 도착률 ≥ {(data.meta.min_arrival * 100).toFixed(0)}%. {Object.values(TEAM_UNIT).join("·")} 배정은 전술 메뉴에서 확인하세요.</p>
    </div>
  );
}
