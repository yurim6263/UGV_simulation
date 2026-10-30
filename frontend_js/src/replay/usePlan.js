import { useEffect, useState } from "react";
import { getPlan } from "../api";

// 편성 계산 결과(지휘관 전용 API)를 한 번 불러온다. 통제관이거나 계산이 없으면 plan 은 null 이다.
export function usePlan(missionId, enabled = true) {
  const [state, setState] = useState({ loading: true, plan: null, cached: false });
  useEffect(() => {
    if (!missionId || !enabled) { setState({ loading: false, plan: null, cached: false }); return undefined; }
    let cancelled = false;
    setState({ loading: true, plan: null, cached: false });
    getPlan(missionId)
      .then((p) => { if (!cancelled) setState({ loading: false, plan: p.status === "COMPLETED" ? p.plan : null, cached: !!p.cached }); })
      .catch(() => { if (!cancelled) setState({ loading: false, plan: null, cached: false }); });
    return () => { cancelled = true; };
  }, [missionId, enabled]);
  return state;
}

// 모드가 우선하는 지표 (편성 계산의 선택 규칙과 같다). 모드 카드에서 강조해 보여 준다.
export const MODE_FOCUS = {
  explore: { desc: "수색 면적 최대", label: "수색 면적", get: (c) => `${(c.v1 * 100).toFixed(1)}%`, tip: "센서로 훑은 면적 비율" },
  rush: { desc: "작전 시간 최소", label: "작전 시간", get: (c) => `${Math.round(c.v2)}분`, tip: "가장 늦게 끝난 제대 기준" },
  balance: { desc: "수색 90% 확보, 부담 최소", label: "운용자 과부하", get: (c) => `${Math.round(c.v3)}분`, tip: "운용자 대기열이 밀린 시간 (수색은 정밀의 90% 이상)" },
};

// 선택한 편성(pick)의 후보 행 (계산 평균 지표)
export function pickRow(plan, mode) {
  const m = plan?.modes?.[mode];
  if (!m) return null;
  const key = m.pick.formation.join("-");
  return m.candidates.find((c) => c.formation.join("-") === key) ?? null;
}
