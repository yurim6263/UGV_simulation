"""
backend/app/weather/forecast_model.py

학습된 ConvLSTM(backend/data/weather/convlstm.pt)로 발표 시각(issue)의 예보를 만든다.
발표 시각까지의 지난 12시간(발표 시각 포함)을 보고 이후 1~3시간을 예측한다. 학습 때와 같은 표준화와 시각 특징을 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from app.weather.convlstm import Seq2SeqConvLSTM
from app.weather.dataset import CHANNELS, HORIZON, LOOKBACK, Normalizer, Region, time_features

CHECKPOINT = Path(__file__).resolve().parents[2] / "data" / "weather" / "convlstm.pt"


class Forecaster:
    def __init__(self, path: Path = CHECKPOINT):
        if not Path(path).exists():
            raise FileNotFoundError(f"학습된 ConvLSTM 이 없습니다: {path} (python scripts/train_convlstm.py)")
        ck = torch.load(path, weights_only=False)
        cfg = ck["config"]
        self.model = Seq2SeqConvLSTM(n_phys=len(CHANNELS), hidden=tuple(cfg["hidden"]), horizon=cfg["horizon"])
        self.model.load_state_dict(ck["state"])
        self.model.eval()
        n = ck["normalizer"]
        self.norm = Normalizer(np.array(n["mean"], dtype="float32"), np.array(n["std"], dtype="float32"))
        self.config = cfg

    @torch.no_grad()
    def predict(self, reg: Region, issue) -> np.ndarray:
        """발표 시각 issue(=입력의 마지막 시각)의 예보 → (HORIZON, C, H, W) 물리값. 바다 칸은 NaN."""
        k = reg.index_of(issue)
        if k < LOOKBACK - 1 or k + 1 > len(reg.times):
            raise ValueError("발표 시각 앞에 12시간의 자료가 없습니다")
        enc = self.norm.encode(reg.data[k - LOOKBACK + 1:k + 1])
        tf = time_features(reg.times[k - LOOKBACK + 1:k + 1 + HORIZON]) if k + HORIZON < len(reg.times) else None
        if tf is None:                                   # 자료 끝에서는 미래 시각 특징을 직접 만든다
            future = reg.times[k] + np.arange(1, HORIZON + 1) * np.timedelta64(1, "h")
            tf = time_features(np.concatenate([reg.times[k - LOOKBACK + 1:k + 1], future]))
        past = torch.from_numpy(enc)[None]
        pt, ft = torch.from_numpy(tf[:LOOKBACK])[None], torch.from_numpy(tf[LOOKBACK:LOOKBACK + HORIZON])[None]
        mask = torch.from_numpy(reg.land.astype("float32"))[None, None]
        out = self.norm.decode(self.model(past, pt, ft, mask).numpy())[0]
        out[:, :, ~reg.land] = np.nan
        return out
