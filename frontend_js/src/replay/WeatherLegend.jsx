import { useEffect, useState } from "react";
import { weatherInfo } from "../api";

// 지도 표시 "기상"의 범례: 0~1 색 막대, 현재 시점의 요인별 값, 시간 변화(작은 그래프), 가정과 한계.
// 원시 기상 자료가 없으면 값을 만들어 보여 주지 않고 이유를 알린다.
const RAMP = "linear-gradient(90deg, rgba(70,150,255,.15), rgba(90,120,255,.55) 40%, rgba(150,90,255,.75) 70%, rgba(235,70,255,.85))";

function Spark({ turns, turn }) {
  const vals = turns.map((t) => t?.index ?? null);
  const known = vals.filter((v) => v !== null);
  if (known.length < 2) return null;
  const w = 180, h = 34;
  const top = Math.max(0.5, Math.max(...known) * 1.2);    // 세로 0 ~ top. 잔잔한 날씨에서도 변화가 보이도록 위쪽 끝을 0.5 이상에서 맞춘다
  const x = (i) => (i / (vals.length - 1)) * w;
  const y = (v) => h - 3 - (v / top) * (h - 6);
  const path = vals.map((v, i) => (v === null ? null : `${i === 0 || vals[i - 1] === null ? "M" : "L"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
  const cur = vals[turn];
  return (
    <svg className="spark" width={w + 30} height={h} viewBox={`0 0 ${w + 30} ${h}`} role="img" aria-label={`기상 악영향 시간 변화 (세로 0~${top.toFixed(2)})`}>
      <line x1="0" x2={w} y1={h - 3} y2={h - 3} stroke="#ffffff22" />
      <text x={w + 4} y={h - 1} fontSize="9" fill="#8b98a7">0</text>
      <text x={w + 4} y="9" fontSize="9" fill="#8b98a7">{top.toFixed(2)}</text>
      <path d={path} fill="none" stroke="#a78bfa" strokeWidth="1.6" />
      {cur !== null && cur !== undefined && <circle cx={x(turn)} cy={y(cur)} r="3.2" fill="#fff" stroke="#a78bfa" strokeWidth="1.6" />}
    </svg>
  );
}

export default function WeatherLegend({ turn }) {
  const [info, setInfo] = useState(null);
  const [help, setHelp] = useState(false);
  useEffect(() => { weatherInfo().then(setInfo).catch((e) => setInfo({ available: false, reason: e.message, notes: [] })); }, []);

  const cur = info?.available ? info.turns[turn] : null;
  return (
    <div className="legend wlegend">
      <b>기상 악영향 (추정) <button className="help-btn" onClick={() => setHelp(!help)} aria-expanded={help} aria-label="기상 지표 설명 펼치기">?</button></b>
      <div className="ramp" style={{ background: RAMP }} aria-hidden="true" />
      <div className="ramp-ends"><span>0 약함</span><span>1 강함</span></div>
      {!info && <small>불러오는 중…</small>}
      {info && !info.available && <p className="wl-warn" role="status"><b>표시할 수 없음</b> {info.reason}</p>}
      {cur && (
        <>
          <div className="wl-main"><span>지표</span><b className="num">{cur.index.toFixed(2)}</b></div>
          <div className="wl-rows">
            <span>비 <b className="num">{cur.rain_mmph.toFixed(1)}</b> mm/h</span>
            <span>안개 가능성 <b className="num">{(cur.fog * 100).toFixed(0)}</b>%</span>
            <span>바람 <b className="num">{cur.wind_ms.toFixed(1)}</b> m/s</span>
            <span>토양수분 <b className="num">{cur.soil_m3m3.toFixed(2)}</b></span>
          </div>
          <Spark turns={info.turns} turn={turn} />
        </>
      )}
      {info?.available && !cur && <small>이 시각은 기상 자료 범위 밖입니다.</small>}
      {info?.available && <small>작전 구역 평균 · 거친 격자(약 11km)를 보간한 값 · 위험도 G/A/R과 다른 척도 · 그래프는 시나리오 5시간의 변화</small>}
      {help && info && (
        <div className="legend-help">
          <p>비, 안개 가능성, 토양수분, 바람을 {Object.entries(info.weights).map(([k, v]) => `${{ rain: "비", fog: "안개", soil: "토양수분", wind: "바람" }[k]} ${v}`).join(", ")} 비중으로 합친 값입니다.</p>
          <ul>{info.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
