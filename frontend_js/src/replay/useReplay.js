import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchServerReplay, overlayUrl as serverOverlayUrl } from "../api";
import { buildReplay, frameForTurn } from "./replayModel";

// 재생 화면의 단일 상태 저장소.
// 지도와 모든 패널(모드, 오버레이, 시간, 제대 필터, 선택 UGV, 이벤트)이 같은 상태를 구독한다.
const FRAME_MS = 120; // 1배속에서 프레임 간격

export function useReplay() {
  const [scenario, setScenario] = useState(null);
  const [models, setModels] = useState(null);
  const [error, setError] = useState("");
  const [unassigned, setUnassigned] = useState(false);   // 이 계정의 제대가 이번 임무에 편성되지 않음

  const [mode, setModeState] = useState("balance");
  const [overlay, setOverlay] = useState("total");
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [teams, setTeams] = useState({ Alpha: true, Bravo: true, Charlie: true });
  const [selected, setSelected] = useState(null); // 에이전트 id

  useEffect(() => {
    let cancelled = false;
    setScenario(null);
    setModels(null);
    setError("");
    setUnassigned(false);
    setFrame(0);
    setPlaying(false);
    setSelected(null);
    (async () => {
      try {
        const { scenario: sc, raws } = await fetchServerReplay();
        if (cancelled) return;
        setScenario(sc);
        setModels(Object.fromEntries(raws.map((r) => [r.mode, buildReplay(r)])));
        setModeState((current) => (raws.some((r) => r.mode === current) ? current : raws[0].mode));
      } catch (e) {
        if (cancelled) return;
        if (e.unassigned) setUnassigned(true);
        else setError(`재생 데이터를 불러오지 못했습니다: ${e.message}`);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 지도 오버레이 이미지 주소 (서버가 그리는 위험도 PNG)
  const overlayUrl = useCallback((kind, turn) => serverOverlayUrl(kind, turn), []);

  const model = models?.[mode] ?? null;
  const lastFrame = model ? model.frames.length - 1 : 0;

  // 자동 재생
  const frameRef = useRef(frame);
  frameRef.current = frame;
  useEffect(() => {
    if (!playing || !model) return undefined;
    const id = setInterval(() => {
      if (frameRef.current >= lastFrame) { setPlaying(false); return; }
      setFrame(frameRef.current + 1);
    }, FRAME_MS / speed);
    return () => clearInterval(id);
  }, [playing, speed, model, lastFrame]);

  // 모드를 바꿔도 같은 시점(턴)을 유지한다
  const setMode = useCallback((next) => {
    if (!models || next === mode) return;
    const turn = models[mode].frames[frameRef.current]?.turn ?? 0;
    setModeState(next);
    setFrame(frameForTurn(models[next], turn));
  }, [models, mode]);

  const seek = useCallback((fi) => {
    setPlaying(false);
    setFrame(Math.max(0, Math.min(fi, lastFrame)));
  }, [lastFrame]);

  const togglePlay = useCallback(() => {
    setPlaying((p) => {
      if (!p && frameRef.current >= lastFrame) setFrame(0);
      return !p;
    });
  }, [lastFrame]);

  const toggleTeam = useCallback((team) => setTeams((t) => ({ ...t, [team]: !t[team] })), []);

  return useMemo(() => ({
    overlayUrl, scenario, models, model, error, unassigned, loading: !error && !unassigned && !model,
    mode, setMode, overlay, setOverlay, frame, seek, lastFrame,
    playing, setPlaying, togglePlay, speed, setSpeed,
    teams, toggleTeam, selected, setSelected,
  }), [overlayUrl, scenario, models, model, error, unassigned, mode, setMode, overlay, frame, seek, lastFrame, playing, togglePlay, speed, teams, toggleTeam, selected]);
}
