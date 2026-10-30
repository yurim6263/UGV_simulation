import { useEffect, useState } from "react";
import { weatherInfo } from "../api";

// 기상 탭: 시나리오 5시간 동안 비, 안개, 토양수분, 바람과 합성 지표(그리고 같은 시점의 위험도)가 어떻게 변하는지 보여 준다.
// 날씨는 구역 안에서 거의 균일해서(ERA5 약 11km 격자) 지도보다 시간 그래프가 정보를 잘 전달한다. 그래프를 누르면 그 시점으로 이동한다.
const W = 320, H = 74, PX = 8, PT = 6, PB = 14;

function Chart({ title, unit, series, domain, turn, onSeek, fmt }) {
  const n = series[0].values.length;
  const [lo, hi] = domain;
  const x = (i) => PX + (i / (n - 1)) * (W - 2 * PX);
  const y = (v) => PT + (1 - (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo || 1)) * (H - PT - PB);
  const path = (vals) => vals.map((v, i) => (v == null ? null : `${i === 0 || vals[i - 1] == null ? "M" : "L"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
  const cur = series[0].values[turn];
  const show = fmt ?? ((v) => v.toFixed(2));
  const seek = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - r.left) / r.width;
    onSeek(Math.round(Math.min(1, Math.max(0, (frac * W - PX) / (W - 2 * PX))) * (n - 1)));
  };
  return (
    <div className="wchart">
      <div className="wc-head">
        <b>{title}</b>
        <span className="num">{cur == null ? "-" : `${show(cur)}${unit}`}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${title} 시간 변화`} onClick={seek} style={{ cursor: "pointer" }}>
        <line x1={PX} x2={W - PX} y1={y(lo)} y2={y(lo)} stroke="#ffffff22" />
        <text x={PX} y={PT + 6} fontSize="9" fill="#8b98a7">{hi}{unit}</text>
        {[0, 6, 12, 18, 24, 30].filter((t) => t < n).map((t) => <text key={t} x={x(t)} y={H - 2} fontSize="9" fill="#8b98a7" textAnchor="middle">{t === 0 ? "시작" : `+${t / 6}h`}</text>)}
        {series.map((s) => <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth="1.8" strokeDasharray={s.dash} />)}
        <line x1={x(turn)} x2={x(turn)} y1={PT} y2={H - PB} stroke="#fff" strokeOpacity=".55" />
        {series.map((s) => s.values[turn] != null && <circle key={s.name} cx={x(turn)} cy={y(s.values[turn])} r="3" fill="#fff" stroke={s.color} strokeWidth="1.6" />)}
      </svg>
      {series.length > 1 && <div className="wc-legend">{series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}</div>}
    </div>
  );
}

const FACTOR = { rain: "비", fog: "안개", soil: "토양수분", wind: "바람" };

export default function WeatherPanel({ turn, onSeek }) {
  const [info, setInfo] = useState(null);
  useEffect(() => { weatherInfo().then(setInfo).catch((e) => setInfo({ available: false, reason: e.message, notes: [] })); }, []);
  if (!info) return <p className="empty">불러오는 중…</p>;
  if (!info.available) return <p className="empty">기상 자료를 표시할 수 없습니다. {info.reason}</p>;

  const col = (k) => info.turns.map((t) => (t ? t[k] : null));
  const finite = (k) => col(k).filter((v) => v != null);
  const maxRain = Math.max(1, Math.ceil(Math.max(...finite("rain_mmph"))));
  const maxWind = Math.max(5, Math.ceil(Math.max(...finite("wind_ms"))));
  return (
    <div className="weather-panel">
      <p className="wp-intro">
        <b>날씨는 5시간 동안 어떻게 변하고, 위험도에 어떻게 반영되나?</b> 구역 평균입니다. 날씨는 구역 안에서 거의 균일해서(ERA5 약 11km 격자) 위치 차이보다 <b>시간 변화</b>가 핵심입니다.
        그래프를 누르면 그 시점으로 이동합니다.
      </p>
      <Chart title="기상 악영향 지표 vs 위험도(종합)" unit="" turn={turn} onSeek={onSeek} domain={[0, 1]}
        series={[{ name: "기상 악영향(추정)", color: "#a78bfa", values: col("index") }, { name: "위험도(종합)", color: "#f0644e", values: col("risk_total"), dash: "4 3" }]} />
      <Chart title="비" unit=" mm/h" turn={turn} onSeek={onSeek} domain={[0, maxRain]} series={[{ name: "비", color: "#4da3ff", values: col("rain_mmph") }]} fmt={(v) => v.toFixed(1)} />
      <Chart title="안개 확률" unit="%" turn={turn} onSeek={onSeek} domain={[0, 100]} series={[{ name: "안개", color: "#9aa7b4", values: col("fog").map((v) => (v == null ? null : v * 100)) }]} fmt={(v) => v.toFixed(0)} />
      <Chart title="토양수분" unit="" turn={turn} onSeek={onSeek} domain={[0, 0.6]} series={[{ name: "토양수분", color: "#c89b5b", values: col("soil_m3m3") }]} />
      <Chart title="바람" unit=" m/s" turn={turn} onSeek={onSeek} domain={[0, maxWind]} series={[{ name: "바람", color: "#5fd0b0", values: col("wind_ms") }]} fmt={(v) => v.toFixed(1)} />
      <details className="wp-notes">
        <summary>이 지표의 가정과 한계</summary>
        <p>비, 안개, 토양수분, 바람을 {Object.entries(info.weights).map(([k, v]) => `${FACTOR[k]} ${v}`).join(", ")} 비중으로 합친 값입니다.</p>
        <ul>{info.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      </details>
    </div>
  );
}
