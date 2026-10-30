"""
backend/app/simulation/algo/environment.py

mumt_sim Environment — 백엔드 통합용 수정본.

데이터 규약:
  - 정적: 지형 parquet (row, col, lc_code, mask_good, roads_*)  — 격자 크기는 데이터에서 읽는다.
  - 동적: 10분 단위 위험도 parquet. 값 컬럼은 normalized_c_total / c_mob_prime / c_sen_prime (0~1).
      actual/sim_cost_map_YYYYMMDD_HHMM.parquet                        → 실황
      forecast/<모델시각 YYYYMMDD_HHMM>/sim_cost_map_<목표시각>.parquet  → 예보
      (구형) 파일명에 시각 2개: <모델시각>_<목표시각>
  - 시각 표기에 24xx(자정 이후 연속 표기, 예: 20230630_2410)가 있으며 다음 날 00:10 으로 해석한다.
  - 동적 파일은 경로 버퍼 안의 셀만 담고 있을 수 있다. 값이 없는 셀은 NaN(= 데이터 없음)으로 두고,
    위험 없음(0)으로 취급하지 않는다.
"""

import glob
import logging
import os
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_STAMP_RE = re.compile(r"\d{8}_\d{4}")
_STEP_DIR_RE = re.compile(r"(\d{8})_(\d{2})$")
from app.simulation.terrain import BLOCKED_COST, DEFAULT_COST_MULT, LC_COST_MULT  # noqa: E402

# 동적 parquet 의 값 컬럼 (우선순위 순). 신규 스키마 → 구형 샘플 스키마.
_VALUE_COLUMNS = {
    "total": ("normalized_c_total", "tactical_cost"),
    "mob": ("c_mob_prime", "mobility_risk"),
    "sen": ("c_sen_prime", "sensor_risk"),
}


def parse_stamp(stamp: str) -> datetime:
    """'YYYYMMDD_HHMM' → datetime. 24xx 같은 자정 이후 연속 표기도 허용한다."""
    day = datetime.strptime(stamp[:8], "%Y%m%d")
    return day + timedelta(hours=int(stamp[9:11]), minutes=int(stamp[11:13]))


class Environment:
    def __init__(self, config):
        self.config = config
        self.static_file = config.TERRAIN_PATH
        self.dynamic_dir = config.DYNAMIC_DIR
        self.grid_size = config.GRID_SIZE
        self.ny, self.nx = self.grid_size

        self.sim_time = None
        self.current_model_time = None

        self.base_layer = np.ones(self.grid_size, dtype=np.float32)
        self.blocked = np.zeros(self.grid_size, dtype=bool)
        self.mask_good = np.zeros(self.grid_size, dtype=bool)
        self.road_dist_m = np.full(self.grid_size, np.nan, dtype=np.float32)
        self.has_road = np.zeros(self.grid_size, dtype=bool)

        # 동적 데이터: kind(total|mob|sen) → {시각: 격자} / {(모델시각, 목표시각): 격자}
        self._actual = {k: {} for k in _VALUE_COLUMNS}
        self._forecast = {k: {} for k in _VALUE_COLUMNS}
        self._model_times: list[datetime] = []
        # 하위 호환 별칭 (total 레이어)
        self.actual_data_pool = self._actual["total"]
        self.global_time_pool = self._forecast["total"]
        self.active_layers = np.full((config.NT, self.ny, self.nx), np.nan, dtype=np.float32)
        self.stats = {"persistence_layers": 0}

        self.comm_mask = np.zeros((self.ny, self.nx), dtype=np.int8)

        self.lc_cost_map = dict(LC_COST_MULT)

        self.masks = {
            f"mask_{r*2:02d}km": self._create_circular_mask(radius=r)
            for r in range(1, 11)
        }

        self.mask_02km = self.masks["mask_02km"]
        self.mask_04km = self.masks["mask_04km"]
        self.mask_06km = self.masks["mask_06km"]
        self.mask_08km = self.masks["mask_08km"]
        self.mask_10km = self.masks["mask_10km"]
        self.mask_12km = self.masks["mask_12km"]
        self.mask_14km = self.masks["mask_14km"]
        self.mask_16km = self.masks["mask_16km"]
        self.mask_18km = self.masks["mask_18km"]
        self.mask_20km = self.masks["mask_20km"]

        # manned_pos는 UGV가 RECALL 모드일 때 참조용 (MannedVehicle.pos 동기화)
        self.manned_pos = np.array([0, 0], dtype=float)

    def _create_circular_mask(self, radius):
        y, x = np.ogrid[-radius: radius + 1, -radius: radius + 1]
        return x ** 2 + y ** 2 <= radius ** 2

    # ── 정적 레이어 ───────────────────────────────────────────────────────

    def load_base_layer(self):
        """정적 지형 parquet → 지형 통행 비용 격자 + 품질/도로 속성 격자."""
        if not os.path.exists(self.static_file):
            raise FileNotFoundError(f"지형 파일 없음: {self.static_file}")

        df = pd.read_parquet(self.static_file)
        rows = df["row"].to_numpy(dtype=int)
        cols = df["col"].to_numpy(dtype=int)
        if rows.max() >= self.ny or cols.max() >= self.nx:
            raise ValueError(
                f"지형 파일 격자({rows.max() + 1}×{cols.max() + 1})가 설정({self.ny}×{self.nx})보다 큽니다."
            )

        codes = np.full(self.grid_size, -1, dtype=np.int32)
        codes[rows, cols] = df["lc_code"].to_numpy(dtype=np.int32)
        if (codes < 0).any():
            raise ValueError(f"지형 파일에 비어 있는 셀이 {int((codes < 0).sum())}개 있습니다.")

        unknown = sorted(set(np.unique(codes).tolist()) - set(self.lc_cost_map))
        if unknown:
            logger.warning("비용표에 없는 lc_code %s → 기본 계수 %.1f 적용", unknown, DEFAULT_COST_MULT)

        lut = np.full(int(codes.max()) + 1, DEFAULT_COST_MULT, dtype=np.float32)
        for code, cost in self.lc_cost_map.items():
            if code < len(lut):
                lut[code] = cost
        self.base_layer = lut[codes]
        self.blocked = self.base_layer >= BLOCKED_COST

        if "mask_good" in df.columns:
            self.mask_good[rows, cols] = df["mask_good"].to_numpy(dtype=bool)
        if "roads_dist_to_drivable_road_m" in df.columns:
            self.road_dist_m[rows, cols] = df["roads_dist_to_drivable_road_m"].to_numpy(dtype=np.float32)
        if "roads_has_drivable_road" in df.columns:
            self.has_road[rows, cols] = df["roads_has_drivable_road"].to_numpy(dtype=bool)

        logger.info("base_layer 로드 완료 shape=%s blocked=%d", self.base_layer.shape, int(self.blocked.sum()))
        return self.base_layer

    # ── 동적 레이어 ───────────────────────────────────────────────────────

    def _read_layers(self, path: str) -> dict:
        """동적 parquet 1개 → {kind: (ny, nx) float32 (없는 셀은 NaN)}."""
        df = pd.read_parquet(path)
        rows = df["row"].to_numpy(dtype=int)
        cols = df["col"].to_numpy(dtype=int)
        inside = (rows >= 0) & (rows < self.ny) & (cols >= 0) & (cols < self.nx)
        if not inside.all():
            logger.warning("%s: 격자 밖 셀 %d개 무시", os.path.basename(path), int((~inside).sum()))

        out = {}
        for kind, candidates in _VALUE_COLUMNS.items():
            col = next((c for c in candidates if c in df.columns), None)
            if col is None:
                if kind == "total":
                    raise KeyError(
                        f"{os.path.basename(path)}: 값 컬럼 {candidates} 중 하나가 필요합니다. 컬럼={list(df.columns)}"
                    )
                continue
            grid = np.full(self.grid_size, np.nan, dtype=np.float32)
            grid[rows[inside], cols[inside]] = df[col].to_numpy(dtype=np.float32)[inside]
            out[kind] = grid
        return out

    def load_all_data(self):
        """
        dynamic_dir 하위의 모든 .parquet 을 실황/예보로 분류해 적재한다.
        읽을 수 없는 파일은 조용히 넘기지 않고 오류로 보고한다.
        """
        files = sorted(glob.glob(os.path.join(self.dynamic_dir, "**", "*.parquet"), recursive=True))
        if not files:
            raise FileNotFoundError(f"동적 데이터 없음: {self.dynamic_dir}")
        logger.info("dynamic 파일 %d개 로드 시작", len(files))

        failures = []
        for f in files:
            rel_parts = os.path.relpath(f, self.dynamic_dir).replace("\\", "/").split("/")
            dir_parts = rel_parts[:-1]
            stamps = _STAMP_RE.findall(os.path.basename(f))
            if not stamps:
                continue
            try:
                target_t = parse_stamp(stamps[-1])
                model_t = None
                if len(stamps) >= 2:                              # 구형: 파일명에 모델/목표 시각
                    model_t = parse_stamp(stamps[0])
                elif "forecast" in dir_parts:                     # forecast/<모델시각>/파일
                    for part in dir_parts:
                        if _STAMP_RE.fullmatch(part):
                            model_t = parse_stamp(part)
                elif dir_parts and dir_parts[0].startswith("Step_"):   # 구형 샘플: Step_01_YYYYMMDD_HH
                    m = _STEP_DIR_RE.search(dir_parts[0])
                    if m:
                        model_t = parse_stamp(f"{m.group(1)}_{m.group(2)}00")
                layers = self._read_layers(f)
            except Exception as exc:  # noqa: BLE001
                failures.append((os.path.basename(f), str(exc)))
                continue

            for kind, grid in layers.items():
                if model_t is None:
                    self._actual[kind][target_t] = grid
                else:
                    self._forecast[kind][(model_t, target_t)] = grid

        if failures:
            for name, err in failures[:5]:
                logger.error("동적 파일 로드 실패 %s: %s", name, err)
            raise ValueError(f"동적 파일 {len(failures)}개를 읽지 못했습니다. 예: {failures[0]}")

        self._model_times = sorted({m for (m, _t) in self._forecast["total"]})
        logger.info(
            "동적 데이터 로드 완료: 실황=%d, 예보=%d (모델 시각 %d개)",
            len(self._actual["total"]), len(self._forecast["total"]), len(self._model_times),
        )

    # ── 시간 레이어 ───────────────────────────────────────────────────────

    def get_layer_idx(self, target_time):
        if self.current_model_time is None:
            return 0
        delta = target_time - self.current_model_time
        idx = int(delta.total_seconds() / 600)
        return max(0, min(idx, self.config.NT - 1))

    def update_forecast_model(self, new_model_time):
        self.current_model_time = new_model_time
        logger.debug("예보 모델 업데이트: %s", new_model_time.strftime('%H:%M'))

    def _resolve_model_time(self, limit=None):
        """limit 시각 이전에 발표된 가장 최근 예보 모델 시각 (없으면 None)."""
        limit = limit or self.current_model_time or self.sim_time
        candidates = [m for m in self._model_times if limit is None or m <= limit]
        return candidates[-1] if candidates else None

    def actual_at(self, t, kind="total"):
        """실행(Execution) 레이어: 시각 t 의 실제 위험도. 없으면 None."""
        return self._actual[kind].get(t)

    def latest_actual_at(self, t, kind="total"):
        """t 이하에서 가장 가까운 실황. 데이터 범위를 벗어나면 마지막 실황을 이어 쓴다."""
        pool = self._actual[kind]
        if t in pool:
            return pool[t]
        earlier = [k for k in pool if k <= t]
        return pool[max(earlier)] if earlier else pool[min(pool)]

    def time_cube(self, sim_time, kind="total", model_time=None):
        """
        계획(Planning) 레이어: (NT, ny, nx). 상태를 바꾸지 않는 순수 조회다.
          i=0 : sim_time 의 실황
          i>0 : 모델 시각(model_time)의 예보. 예보가 없으면 직전 레이어를 이어 쓴다(persistence).
                미래의 실황을 대신 쓰지 않는다 — 계획 단계가 정답을 보면 안 되기 때문이다.
        데이터가 전혀 없는 레이어는 NaN(= 알 수 없음)이다.
        """
        if model_time is None:
            model_time = self._resolve_model_time(sim_time)
        layers = []
        for i in range(self.config.NT):
            target_t = sim_time + timedelta(minutes=i * 10)
            layer = None
            if i == 0:
                layer = self._actual[kind].get(target_t)
            if layer is None and model_time is not None:
                layer = self._forecast[kind].get((model_time, target_t))
            if layer is None and i > 0 and layers:
                layer = layers[-1]
                self.stats["persistence_layers"] += 1
            if layer is None:
                layer = np.full(self.grid_size, np.nan, dtype=np.float32)
            layers.append(layer)
        return np.stack(layers, axis=0)

    def get_time_cube(self, kind="total"):
        if self.sim_time is None:
            raise RuntimeError("sim_time 이 설정되지 않았습니다.")
        return self.time_cube(self.sim_time, kind, self._resolve_model_time())

    def get_active_time_cube(self):
        self.active_layers = self.get_time_cube("total")
        return self.active_layers

    def model_time_at(self, t):
        """시각 t 에 이미 발표되어 있던 가장 최근 예보의 발표 시각 (없으면 None)."""
        return self._resolve_model_time(t)

    def forecast_layer(self, kind, model_time, target_t):
        """발표 시각 model_time 의 예보 중 목표 시각 target_t 의 위험도 격자. 없으면 None (지속성으로 채우지 않는다)."""
        return self._forecast[kind].get((model_time, target_t))

    @property
    def start_time(self):
        """데이터가 있는 가장 이른 실황 시각."""
        return min(self._actual["total"]) if self._actual["total"] else None

    def mask_arsenal(self):
        """반경(셀) → 원형 불리언 마스크. 센서 시야 반경이 바뀔 때 꺼내 쓴다."""
        return {r: self._create_circular_mask(r) for r in range(1, 11)}

    # ── 통신 마스크 ───────────────────────────────────────────────────────

    def update_comm_mask(self, manned_pos):
        self.comm_mask.fill(0)
        self.manned_pos = np.array(manned_pos, dtype=float)
        cy, cx = int(manned_pos[0]), int(manned_pos[1])
        self._apply_mask_to_grid(cy, cx, self.mask_18km, value=1)
        self._apply_mask_to_grid(cy, cx, self.mask_12km, value=2)

    def _apply_mask_to_grid(self, cy, cx, mask, value):
        r = mask.shape[0] // 2
        y_min = max(0, cy - r)
        y_max = min(self.ny, cy + r + 1)
        x_min = max(0, cx - r)
        x_max = min(self.nx, cx + r + 1)

        my_min = y_min - (cy - r)
        my_max = my_min + (y_max - y_min)
        mx_min = x_min - (cx - r)
        mx_max = mx_min + (x_max - x_min)

        valid_mask = mask[my_min:my_max, mx_min:mx_max]
        target_area = self.comm_mask[y_min:y_max, x_min:x_max]
        target_area[valid_mask] = value
