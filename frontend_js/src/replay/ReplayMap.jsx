import { useEffect, useMemo } from "react";
import L from "leaflet";
import { CircleMarker, ImageOverlay, MapContainer, Marker, Polyline, Tooltip } from "react-leaflet";
import BaseMap from "./BaseMap";
import { GRADE_COLOR, TEAM_COLOR, agentLabel, pathAt, stateAt } from "./replayModel";

const dotIcon = (color) => L.divIcon({
  html: `<div class="leaflet-marker-dot" style="background:${color}"></div>`,
  iconSize: [16, 16], iconAnchor: [8, 8], className: "leaflet-marker-wrapper",
});
const starIcon = (color) => L.divIcon({
  html: `<div class="replay-star" style="color:${color}">★</div>`,
  iconSize: [24, 24], iconAnchor: [12, 12], className: "leaflet-marker-wrapper",
});

// 지도는 그리기만 한다. 모드·오버레이·시간·제대 필터·선택은 모두 밖(useReplay)에서 온다.
export default function ReplayMap({ replay, allowedTeams }) {
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

  const poiOwner = useMemo(() => {
    const owner = {};
    Object.entries(model.kpi.per_team).forEach(([team, v]) => { if (v.poi) owner[v.poi] = team; });
    return owner;
  }, [model]);

  return (
    <MapContainer bounds={scenario.bounds} boundsOptions={{ padding: [6, 6] }} zoomControl attributionControl={false}>
      <BaseMap />
      <ImageOverlay
        url={overlayUrl(overlay, turn)}
        bounds={scenario.bounds}
        opacity={0.6}
        className="replay-overlay"
        interactive={false}
      />

      <Marker position={scenario.start} icon={dotIcon("#e67e22")} interactive={false}>
        <Tooltip permanent direction="top" offset={[0, -12]}>출발지</Tooltip>
      </Marker>
      {scenario.pois.map((p) => (
        <Marker key={p.id} position={[p.lat, p.lon]} icon={dotIcon(TEAM_COLOR[poiOwner[p.id]] ?? "#94a3b8")} interactive={false}>
          <Tooltip permanent direction="top" offset={[0, -12]}>POI-{p.id}</Tooltip>
        </Marker>
      ))}

      {visible.map(({ agent, i }) => {
        const color = TEAM_COLOR[agent.team];
        const path = pathAt(model, frame, i);
        return path.length > 1 ? (
          <Polyline
            key={`path-${agent.id}`}
            positions={path}
            pathOptions={{ color, weight: agent.kind === "Manned" ? 4 : 3, opacity: 0.9, dashArray: agent.kind === "Manned" ? null : "6,6" }}
          />
        ) : null;
      })}

      {visible.map(({ agent, i }) => {
        const s = stateAt(model, frame, i);
        if (!s) return null;
        const pos = [s.lat, s.lon];
        const select = { click: () => setSelected(agent.id) };
        const tip = <Tooltip>{agentLabel(agent)}</Tooltip>;
        return agent.kind === "Manned" ? (
          <Marker key={agent.id} position={pos} icon={starIcon(TEAM_COLOR[agent.team])} eventHandlers={select}>{tip}</Marker>
        ) : (
          <CircleMarker
            key={agent.id}
            center={pos}
            radius={selected === agent.id ? 9 : 6}
            pathOptions={{ color: selected === agent.id ? "#fff" : TEAM_COLOR[agent.team], weight: 2, fillColor: GRADE_COLOR[s.grade], fillOpacity: 1 }}
            eventHandlers={select}
          >
            {tip}
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
