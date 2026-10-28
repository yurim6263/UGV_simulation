import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../api";
import ReplayMap from "./ReplayMap";
import { clockText } from "./clock";
import { GRADE_COLOR } from "./replayModel";

// 예보 탭: 현재 시각에 이미 발표되어 있던 예보로 "현재 + N시간 뒤"의 위험도를 같은 지도 스타일과 아이콘으로 보여 준다.
// 예보가 없는 시각은 실황이나 지속성으로 채우지 않고 "예보 없음"으로 표시한다.
const LEADS = [[0, "현재 시점"], [60, "+1시간"], [120, "+2시간"], [180, "+3시간"]];
const BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";   // 투명 1px

// 한 줄짜리 G/A/R 비율 막대 (예보와 실제를 나란히 비교한다)
function ShareBar({ label, share }) {
  const pct = (v) => Math.round(v * 100);
  return (
    <div className="share-row">
      <span>{label}</span>
      <div className="share-bar" title={`안전 ${pct(share.G)}% · 주의 ${pct(share.A)}% · 고위험 ${pct(share.R)}%`}>
        {["G", "A", "R"].map((g) => <i key={g} style={{ width: `${share[g] * 100}%`, background: GRADE_COLOR[g] }} />)}
      </div>
      <em>고위험 {pct(share.R)}%</em>
    </div>
  );
}

export default function ForecastPanel({ replay, allowedTeams }) {
  const [lead, setLead] = useState(60);
  const [info, setInfo] = useState(null);
  const turn = replay.model.frames[replay.frame].turn;
  const kind = replay.overlay;

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/map/forecast-info?turn=${turn}&lead_min=${lead}&kind=${kind}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then((d) => { if (!cancelled) setInfo(d); })
      .catch(() => { if (!cancelled) setInfo({ available: false, reason: "예보 정보를 불러오지 못했습니다." }); });
    return () => { cancelled = true; };
  }, [turn, lead, kind]);

  // 지도는 재생 화면과 같은 컴포넌트(경로, UGV, 유인기, 출발지, POI 아이콘)를 쓰고, 위험도 이미지만 예보로 바꾼다
  const forecastReplay = useMemo(() => ({
    ...replay,
    overlayUrl: (k, t) => (info?.available ? `${API_URL}/api/map/forecast/${k}/${t}/${lead}.png` : BLANK),
  }), [replay, info, lead]);

  return (
    <div className="forecast">
      <div className="seg" role="group" aria-label="예보 시점">
        {LEADS.map(([min, label]) => (
          <button key={min} className={lead === min ? "on" : ""} onClick={() => setLead(min)}>{label}</button>
        ))}
      </div>
      <p className="fc-info">
        {info?.model_time
          ? <>발표 <b>{clockText(info.model_time)}</b> 예보 → 대상 <b>{clockText(info.target_time)}</b> <span>(현재 {clockText(info.current_time)})</span></>
          : "예보 정보를 불러오는 중…"}
      </p>
      {info?.forecast_share && (
        <div className="fc-shares" aria-label="등급 비율 비교">
          <ShareBar label="예보" share={info.forecast_share} />
          {info.actual_share ? <ShareBar label="실제" share={info.actual_share} /> : <p className="hint tight">이 시각의 실황 데이터는 없습니다.</p>}
        </div>
      )}
      <div className="replay-map mini-map">
        <ReplayMap replay={forecastReplay} allowedTeams={allowedTeams} compact />
        {info && !info.available && <div className="fc-none">예보 없음<small>{info.reason}</small></div>}
      </div>
      <p className="hint tight">
        위 막대는 같은 시각의 안전·주의·고위험 칸 비율입니다. <b>예보는 실제보다 위험을 훨씬 낮게 보는 경향이 있어</b> +1시간부터는 대부분 안전(옅은 초록)으로 나와 지도에 색이 거의 안 보입니다 (기상 모델 보고서).
        예보 발표는 3번(22:00, 23:00, 00:00)뿐이고 발표 후 3시간까지만 있습니다. 범위를 벗어나면 실황으로 채우지 않고 "예보 없음"으로 둡니다.
      </p>
    </div>
  );
}
