import { useEffect, useMemo } from "react";
import { ImageOverlay, MapContainer, Marker, Polyline, Tooltip } from "react-leaflet";
import BaseMap from "./BaseMap";
import { mannedIcon, headingDeg, startIcon, targetIcon, ugvIcon } from "./mapMarkers";
import { TEAM_COLOR, TEAM_UNIT, agentLabel, pathAt, stateAt } from "./replayModel";

const CASING = "#070b10";
const ALARM = new Set(["SOS_SENSOR", "SOS_MOBILITY", "SOS_WAIT", "BLIND"]);

// 경로: 어두운 테두리 위에 색선을 얹어 위험도 색 위에서도 보이게 한다. 지나온 지 오래된 구간은 옅게 그린다.
function Route({ path, color, weight, dim }) {
  const cut = Math.floor(path.length * 0.45);
  const round = { lineCap: "round", lineJoin: "round" };
  return (
    <>
      <Polyline positions={path} interactive={false} pathOptions={{ color: CASING, weight: weight + 3, opacity: dim ? 0.4 : 0.85, ...round }} />
      <Polyline positions={path.slice(0, cut + 1)} interactive={false} pathOptions={{ color, weight, opacity: dim ? 0.2 : 0.5, ...round }} />
      <Polyline positions={path.slice(cut)} interactive={false} pathOptions={{ color, weight, opacity: dim ? 0.4 : 1, ...round }} />
    </>
  );
}

// 지도는 그리기만 한다. 모드·오버레이·시간·제대 필터·선택은 모두 밖(useReplay)에서 온다.
export default function ReplayMap({ replay, allowedTeams, compact = false }) {
  const { overlayUrl, scenario, model, frame, overlay, teams, selected, setSelected } = replay;
  const turn = model.frames[frame].turn;
  const nextTurn = Math.min(turn + 1, scenario.turns - 1);

  // 다음 턴 오버레이를 미리 받아 깜빡임을 줄인다
  useEffect(() => {
    const img = new Image();
    img.src = overlayUrl(overlay, nextTurn);
  }, [overlayUrl, overlay, nextTurn]);

  const visible = useMemo(
    () => model.agents
      .map((agent, i) => ({ agent, i }))
      .filter(({ agent }) => agent.kind !== "OP" && teams[agent.team] && (!allowedTeams || allowedTeams.includes(agent.team))),
    [model, teams, allowedTeams],
  );

  const drawn = useMemo(
    () => visible.map(({ agent, i }) => ({ agent, path: pathAt(model, frame, i), s: stateAt(model, frame, i) })),
    [visible, model, frame],
  );

  const poiOwner = useMemo(() => {
    const owner = {};
    Object.entries(model.kpi.per_team).forEach(([team, v]) => { if (v.poi) owner[v.poi] = team; });
    return owner;
  }, [model]);

  const hasSelection = drawn.some(({ agent }) => agent.id === selected);

  return (
    <MapContainer
      bounds={scenario.bounds} zoomControl attributionControl={false} zoomSnap={0.1} zoomDelta={0.5}
      boundsOptions={{ paddingTopLeft: [4, 4], paddingBottomRight: [4, compact ? 4 : 84] }}
    >
      <BaseMap />
      <ImageOverlay
        url={overlayUrl(overlay, turn)}
        bounds={scenario.bounds}
        opacity={0.6}
        className="replay-overlay"
        interactive={false}
      />

      <Marker position={scenario.start} icon={startIcon()} interactive={false}>
        <Tooltip permanent direction="top" offset={[0, -34]}>출발지</Tooltip>
      </Marker>
      {scenario.pois.map((p) => {
        const owner = poiOwner[p.id];
        return (
          <Marker key={p.id} position={[p.lat, p.lon]} icon={targetIcon(TEAM_COLOR[owner] ?? "#94a3b8", p.id)} interactive={false}>
            <Tooltip permanent direction="top" offset={[0, -24]}>목표 {p.id}{owner ? ` · ${TEAM_UNIT[owner]}` : ""}</Tooltip>
          </Marker>
        );
      })}

      {/* UGV 경로를 먼저, 유인기 경로를 위에 그린다. 선택한 UGV 만 굵게 하고 나머지는 흐리게 한다. */}
      {drawn.filter(({ agent, path }) => agent.kind === "UGV" && path.length > 1).map(({ agent, path }) => {
        const sel = agent.id === selected;
        return <Route key={`path-${agent.id}`} path={path} color={TEAM_COLOR[agent.team]} weight={sel ? 4.5 : 2.2} dim={hasSelection && !sel} />;
      })}
      {drawn.filter(({ agent, path }) => agent.kind === "Manned" && path.length > 1).map(({ agent, path }) => (
        <Route key={`path-${agent.id}`} path={path} color={TEAM_COLOR[agent.team]} weight={4} dim={false} />
      ))}

      {drawn.map(({ agent, path, s }) => {
        if (!s) return null;
        const pos = [s.lat, s.lon];
        const select = { click: () => setSelected(agent.id) };
        const tip = <Tooltip offset={[0, -12]}>{agentLabel(agent)}</Tooltip>;
        if (agent.kind === "Manned") {
          const heading = path.length > 1 ? headingDeg(path[path.length - 2], path[path.length - 1]) : 0;
          return <Marker key={agent.id} position={pos} icon={mannedIcon(TEAM_COLOR[agent.team], heading)} zIndexOffset={300} eventHandlers={select}>{tip}</Marker>;
        }
        const sel = agent.id === selected;
        return (
          <Marker
            key={agent.id} position={pos} zIndexOffset={sel ? 500 : 100} eventHandlers={select}
            icon={ugvIcon(TEAM_COLOR[agent.team], s.grade, { alarm: ALARM.has(s.action), selected: sel })}
          >
            {tip}
          </Marker>
        );
      })}
    </MapContainer>
  );
}
