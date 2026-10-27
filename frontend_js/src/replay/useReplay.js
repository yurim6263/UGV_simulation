import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchServerReplay, overlayUrl as serverOverlayUrl } from "../api";
import { buildReplay, frameForTurn, replayBase } from "./replayModel";

// 재생 화면의 단일 상태 저장소.
// 지도와 모든 패널(모드, 오버레이, 시간, 제대 필터, 선택 UGV, 이벤트)이 같은 상태를 구독한다.
const FRAME_MS = 120; // 1배속에서 프레임 간격

export function useReplay(source = "server") {
  const base = replayBase(source);
  const [scenario, setScenario] = useState(null);
  const [models, setModels] = useState(null);
  const [error, setError] = useState("");

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
    setFrame(0);
    setPlaying(false);
    setSelected(null);
    (async () => {
      try {
        let sc;
        let raws;
        if (source === "server") {
          ({ scenario: sc, raws } = await fetchServerReplay());
        } else {
          sc = await (await fetch(`${base}/scenario.json`)).json();
          raws = await Promise.all(
            sc.modes.map(async (m) => {
              const res = await fetch(`${base}/${m.key}.json`);
              if (!res.ok) throw new Error(`${m.key}.json (${res.status})`);
              return res.json();
            }),
          );
        }
        if (cancelled) return;
        setScenario(sc);
        setModels(Object.fromEntries(raws.map((r) => [r.mode, buildReplay(r)])));
        setModeState((current) => (raws.some((r) => r.mode === current) ? current : raws[0].mode));
      } catch (e) {
        if (!cancelled) setError(`재생 데이터를 불러오지 못했습니다: ${e.message}`);
      }
    })();
    return () => { cancelled = true; };
  }, [source, base]);

  // 지도 오버레이 이미지 주소: 서버 실행은 API, 정적 출처는 변환 스크립트가 만든 PNG
  const overlayUrl = useCallback(
    (kind, turn) => (source === "server" ? serverOverlayUrl(kind, turn) : `${base}/overlay/${kind}/${turn}.png`),
    [source, base],
  );

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
    source, base, overlayUrl, scenario, models, model, error, loading: !error && !model,
    mode, setMode, overlay, setOverlay, frame, seek, lastFrame,
    playing, setPlaying, togglePlay, speed, setSpeed,
    teams, toggleTeam, selected, setSelected,
  }), [source, base, overlayUrl, scenario, models, model, error, mode, setMode, overlay, frame, seek, lastFrame, playing, togglePlay, speed, teams, toggleTeam, selected]);
}
