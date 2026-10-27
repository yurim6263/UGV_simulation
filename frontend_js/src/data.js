export const accounts = {
  admin: { password: "admin", role: "commander", label: "지휘관" },
  user1: { password: "user1", role: "controller", label: "1제대 통제관", unit: "1제대" },
  user2: { password: "user2", role: "controller", label: "2제대 통제관", unit: "2제대" },
  user3: { password: "user3", role: "controller", label: "3제대 통제관", unit: "3제대" },
};

export const initialTargets = {
  user1: { title: "도착지1", lat: "", lng: "", recon: "" },
  user2: { title: "도착지2", lat: "", lng: "", recon: "" },
  user3: { title: "도착지3", lat: "", lng: "", recon: "" },
};

export const units = [
  { key: "user1", name: "1제대", color: "#f97316", success: 78, risk: 35, depart: "02:20:00", arrive: "05:20:00" },
  { key: "user2", name: "2제대", color: "#22d3ee", success: 64, risk: 57, depart: "02:10:00", arrive: "05:50:00" },
  { key: "user3", name: "3제대", color: "#f472b6", success: 86, risk: 22, depart: "02:30:00", arrive: "06:10:00" },
];

export const ltwrMaps = [
  { title: "현재 + 1시간 뒤 예측", file: "/map_01_Tactical_Weighted_Cost_1h.html" },
  { title: "현재 + 2시간 뒤 예측", file: "/map_01_Tactical_Weighted_Cost_2h.html" },
  { title: "현재 + 3시간 뒤 예측", file: "/map_01_Tactical_Weighted_Cost_3h.html" },
];
