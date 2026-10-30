import { useEffect, useRef, useState } from "react";
import { AttributionControl, TileLayer } from "react-leaflet";

// 어두운 바탕 지도 (인터넷 필요). 타일을 받지 못하면 바탕 지도를 빼고
// 위험도 이미지·경로·표식만 보이게 하고, 인터넷이 돌아오면(또는 1분 뒤) 다시 시도한다.
// API 키 없이 쓸 수 있는 OpenStreetMap 타일을 CSS 필터로 어둡게 만든다 (styles.css 의 .basemap-dark).
// (CARTO dark_all 은 키 없이는 "API KEY REQUIRED" 워터마크가 찍혀 쓸 수 없었다.)
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const FAIL_AFTER = 4;          // 타일 하나도 받지 못한 채 연속 실패가 이만큼이면 오프라인으로 본다
const RETRY_MS = 60_000;

export default function BaseMap() {
  const [offline, setOffline] = useState(() => typeof navigator !== "undefined" && navigator.onLine === false);
  const errors = useRef(0);

  useEffect(() => {
    const up = () => { errors.current = 0; setOffline(false); };
    const down = () => setOffline(true);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, []);

  // 브라우저는 온라인이라는데 타일 서버만 막힌 경우를 위해 주기적으로 다시 시도한다
  useEffect(() => {
    if (!offline) return undefined;
    const timer = setTimeout(() => { errors.current = 0; setOffline(false); }, RETRY_MS);
    return () => clearTimeout(timer);
  }, [offline]);

  if (offline) return null;
  return (
    <>
      <AttributionControl prefix={false} />
      <TileLayer
        url={TILES}
        className="basemap-dark"
        maxZoom={19}
        attribution={ATTRIBUTION}
        eventHandlers={{
          tileload: () => { errors.current = 0; },
          tileerror: () => { errors.current += 1; if (errors.current >= FAIL_AFTER) setOffline(true); },
        }}
      />
    </>
  );
}
