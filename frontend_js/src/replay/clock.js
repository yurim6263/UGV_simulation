// 시나리오 시각 도우미.
// 데이터의 시각은 표준 시간대 정보가 없는 "YYYY-MM-DDTHH:MM:SS" 이다. 브라우저 시간대에 흔들리지 않게 숫자로 직접 계산한다.
function parseNaive(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso ?? "");
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null;
}

// "6/30 22:10" 형태. 해석할 수 없는 값이면 null.
export function clockText(iso, addMinutes = 0) {
  const t = parseNaive(iso);
  if (t === null) return null;
  const d = new Date(t + addMinutes * 60000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

// 제대가 실제로 움직이기 시작한 턴 (출격 지연이 있으면 0 이 아니다). 기록이 없으면 null.
export function teamLaunchTurn(model, team) {
  let best = null;
  model.tracks.forEach((track, i) => {
    const a = model.agents[i];
    if (a.kind !== "UGV" || a.team !== team) return;
    const first = track.find((s) => s.action !== "IDLE");
    if (first && (best === null || first.turn < best)) best = first.turn;
  });
  return best;
}
