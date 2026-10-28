import L from "leaflet";
import { GRADE_COLOR } from "./replayModel";

// 지도 아이콘. 모양은 역할, 색은 제대, UGV 의 안쪽 색은 위험 등급(상태)이다.
// 같은 모양은 한 번만 만들어 재사용한다 (재생 중 프레임마다 아이콘을 새로 만들지 않기 위해).
const DARK = "#070b10";
export const ICON_SCALE = 2 / 3;                 // 아이콘 표시 크기 (그린 크기 대비)
const cache = new Map();
const once = (key, build) => {
  if (!cache.has(key)) cache.set(key, build());
  return cache.get(key);
};
const icon = (svg, size, anchor) => {
  const px = (v) => Math.round(v * ICON_SCALE);
  const sized = svg.replace(/width="(\d+)" height="(\d+)"/, (_, w, h) => `width="${px(w)}" height="${px(h)}"`);
  return L.divIcon({ html: sized, iconSize: [px(size[0]), px(size[1])], iconAnchor: [px(anchor[0]), px(anchor[1])], className: "leaflet-marker-wrapper" });
};

// UGV: 안쪽 = 상태색(G/A/R), 테두리 = 제대색. 경보(SOS, 시야 상실)면 고리가 번져 나가고, 선택되면 흰 고리가 생긴다.
export function ugvIcon(teamColor, grade, { alarm = false, selected = false } = {}) {
  return once(`u|${teamColor}|${grade}|${alarm}|${selected}`, () => {
    const r = selected ? 10 : 8;
    return icon(
      `<svg class="mk" width="44" height="44" viewBox="0 0 44 44">`
      + (alarm ? `<circle class="mk-pulse" cx="22" cy="22" r="11" fill="none" stroke="${GRADE_COLOR.R}" stroke-width="2.5"/>` : "")
      + (selected ? `<circle cx="22" cy="22" r="17" fill="none" stroke="#fff" stroke-width="1.8"/>` : "")
      + `<circle cx="22" cy="22" r="${r + 2.8}" fill="none" stroke="${DARK}" stroke-opacity=".85" stroke-width="1.6"/>`
      + `<circle cx="22" cy="22" r="${r}" fill="${GRADE_COLOR[grade] ?? "#94a3b8"}" stroke="${teamColor}" stroke-width="4"/>`
      + `</svg>`,
      [44, 44], [22, 22],
    );
  });
}

// 유인기: 진행 방향을 가리키는 화살표 (방향은 5도 단위로 맞춘다)
export function mannedIcon(teamColor, heading = 0) {
  const deg = Math.round(heading / 5) * 5;
  return once(`m|${teamColor}|${deg}`, () => icon(
    `<svg class="mk" width="44" height="44" viewBox="0 0 44 44"><g transform="translate(22 22) rotate(${deg}) scale(1.15)">`
    + `<path d="M0 -13 L9.5 10 L0 5.5 L-9.5 10 Z" fill="${teamColor}" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></g></svg>`,
    [44, 44], [22, 22],
  ));
}

// 목표: 조준 아이콘 안에 번호, 색은 담당 제대
export function targetIcon(teamColor, no) {
  return once(`t|${teamColor}|${no}`, () => icon(
    `<svg class="mk" width="52" height="52" viewBox="0 0 52 52">`
    + `<circle cx="26" cy="26" r="14" fill="#0e151d" fill-opacity=".88" stroke="${teamColor}" stroke-width="2.6"/>`
    + `<path d="M26 5V12M26 40V47M5 26H12M40 26H47" stroke="${teamColor}" stroke-width="2.6" stroke-linecap="round"/>`
    + `<text x="26" y="31.5" text-anchor="middle" font-size="15" font-weight="700" fill="#fff" font-family="inherit">${no}</text></svg>`,
    [52, 52], [26, 26],
  ));
}

// 출발지: 깃발 핀 (끝이 위치)
export function startIcon() {
  return once("s", () => icon(
    `<svg class="mk" width="36" height="42" viewBox="0 0 36 42">`
    + `<path d="M18 40 L7 20 A11 11 0 1 1 29 20 Z" fill="#e67e22" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/>`
    + `<path d="M15 25V12L25 15.5L15 19" fill="#fff"/></svg>`,
    [36, 42], [18, 40],
  ));
}

// 지도 위 두 점 사이의 진행 방향 (북쪽 기준 시계방향 도)
export function headingDeg(from, to) {
  const dLat = to[0] - from[0];
  const dLon = (to[1] - from[1]) * Math.cos((to[0] * Math.PI) / 180);
  return (Math.atan2(dLon, dLat) * 180) / Math.PI;
}
