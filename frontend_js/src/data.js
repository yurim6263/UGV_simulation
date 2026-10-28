// 계정은 서버(DB)가 관리한다. 여기에는 화면 표시용 기본값만 둔다.
// 목표 좌표 기본값: 팀원 시뮬레이션의 정찰지 3곳 (작전 구역 안). 정찰 시간은 분 단위.
export const initialTargets = {
  user1: { title: "도착지1", lat: "54.40", lng: "18.54", recon: "30" },
  user2: { title: "도착지2", lat: "54.33", lng: "18.36", recon: "30" },
  user3: { title: "도착지3", lat: "54.37", lng: "18.50", recon: "30" },
};

export const units = [
  { key: "user1", name: "1제대", color: "#4d8dff", success: 78, risk: 35, depart: "02:20:00", arrive: "05:20:00" },
  { key: "user2", name: "2제대", color: "#b07cff", success: 64, risk: 57, depart: "02:10:00", arrive: "05:50:00" },
  { key: "user3", name: "3제대", color: "#ff8fb1", success: 86, risk: 22, depart: "02:30:00", arrive: "06:10:00" },
];

export const ltwrMaps = [
  { title: "현재 + 1시간 뒤 예측", file: "/map_01_Tactical_Weighted_Cost_1h.html" },
  { title: "현재 + 2시간 뒤 예측", file: "/map_01_Tactical_Weighted_Cost_2h.html" },
  { title: "현재 + 3시간 뒤 예측", file: "/map_01_Tactical_Weighted_Cost_3h.html" },
];
