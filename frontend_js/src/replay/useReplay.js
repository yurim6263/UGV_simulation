import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchAssigned, fetchServerReplay, overlayUrl as serverOverlayUrl, setTeamModes } from "../api";
import { buildReplay, frameForTurn } from "./replayModel";

// 재생 화면의 단일 상태 저장소.
// 지도와 모든 패널(모드, 오버레이, 시간, 제대 필터, 선택 UGV, 이벤트)이 같은 상태를 구독한다.
const FRAME_MS = 120; // 1배속에서 프레임 간격

export function useReplay() {
  const [scenario, setScenario] = useState(null);
  const [models, setModels] = useState(null);
  const [error, setError] = useState("");
  const [unassigned, setUnassigned] = useState(false);   // 이 계정의 제대가 이번 임무에 편성되지 않음
  const [teamModes, setTeamModesState] = useState({});     // 제대별 지정 모드 { Alpha: "balance", ... } (통제관은 담당 제대 것만)
  const [assignError, setAssignError] = useState("");

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
        setTeamModesState(sc.team_modes ?? {});
        setModels(Object.fromEntries(raws.map((r) => [r.mode, buildReplay(r)])));
        setModeState(raws.some((r) => r.mode === "assigned") ? "assigned" : (current) => (raws.some((r) => r.mode === current) ? current : raws[0].mode));
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

  // 제대의 모드를 바꾼다: 서버에 저장하고, 지정 편성을 다시 합친다 (시뮬레이션을 다시 돌리지 않는다)
  const assignMode = useCallback(async (team, nextMode) => {
    if (!scenario || teamModes[team] === nextMode) return;
    setAssignError("");
    try {
      const saved = await setTeamModes(scenario.mission_id, { [team]: nextMode });
      const raw = (await fetchAssigned(scenario.mission_id)).mode;
      setTeamModesState(saved.team_modes);
      setModels((current) => ({ ...current, assigned: buildReplay(raw) }));
      setFrame((f) => Math.min(f, Math.max(0, raw.steps.length - 1)));
    } catch (e) {
      setAssignError(e.message);
    }
  }, [scenario, teamModes]);

  // 모든 제대에 같은 모드를 지정한다 (모드 카드를 누를 때). 한 번의 저장과 한 번의 합성만 한다.
  const assignAll = useCallback(async (nextMode) => {
    if (!scenario) return;
    const teams = Object.keys(teamModes);
    if (teams.length && teams.every((t) => teamModes[t] === nextMode)) return;
    setAssignError("");
    try {
      const saved = await setTeamModes(scenario.mission_id, Object.fromEntries(teams.map((t) => [t, nextMode])));
      const raw = (await fetchAssigned(scenario.mission_id)).mode;
      setTeamModesState(saved.team_modes);
      setModels((current) => ({ ...current, assigned: buildReplay(raw) }));
      setFrame((f) => Math.min(f, Math.max(0, raw.steps.length - 1)));
    } catch (e) {
      setAssignError(e.message);
    }
  }, [scenario, teamModes]);

  const toggleTeam = useCallback((team) => setTeams((t) => ({ ...t, [team]: !t[team] })), []);

  return useMemo(() => ({
    overlayUrl, scenario, models, model, error, unassigned, loading: !error && !unassigned && !model,
    teamModes, assignMode, assignAll, assignError,
    mode, setMode, overlay, setOverlay, frame, seek, lastFrame,
    playing, setPlaying, togglePlay, speed, setSpeed,
    teams, toggleTeam, selected, setSelected,
  }), [overlayUrl, scenario, models, model, error, unassigned, teamModes, assignMode, assignAll, assignError, mode, setMode, overlay, frame, seek, lastFrame, playing, togglePlay, speed, teams, toggleTeam, selected]);
}
