"""
backend/app/weather/convlstm.py

Seq2Seq ConvLSTM 기상 예측 모델 (PyTorch). 결과보고서의 최종 채택 구조(인코더 ConvLSTM → 디코더 ConvLSTM)를 이 저장소에서 새로 구현한 것이다.
팀 원본 코드는 저장소에 없어서 세부(층 수, 은닉 크기, 손실, 학습 설정)는 우리가 정했다. 원본과 같다고 말하지 않는다.

  입력  : 지난 12시간의 (표준화된) 7개 물리 채널 + 시각/연중일 sin·cos 4채널 + 육지 마스크 1채널
  출력  : 이후 1~3시간의 7개 채널. 디코더는 앞 시각 예측을 받아 다음 시각을 낸다 (자기회귀).
  잔차  : 예측 = 직전 프레임 + 보정값. 아무것도 배우지 못하면 지속성 예보가 되므로, 기준선보다 나빠지기 어렵게 하는 구조다.
          (그래서 "지속성보다 낫다"는 주장은 반드시 시험 구간에서 따로 확인한다: weather_eval)
  손실  : 육지 칸만의 평균제곱오차 (바다 칸은 ERA5-Land 에 값이 없다).
"""

from __future__ import annotations

import torch
from torch import nn


class ConvLSTMCell(nn.Module):
    def __init__(self, in_ch: int, hid: int, k: int = 3):
        super().__init__()
        self.hid = hid
        self.gates = nn.Conv2d(in_ch + hid, 4 * hid, k, padding=k // 2)

    def forward(self, x, state):
        h, c = state
        i, f, o, g = torch.chunk(self.gates(torch.cat([x, h], dim=1)), 4, dim=1)
        c = torch.sigmoid(f) * c + torch.sigmoid(i) * torch.tanh(g)
        h = torch.sigmoid(o) * torch.tanh(c)
        return h, c

    def zeros(self, b: int, hw: tuple[int, int], device) -> tuple[torch.Tensor, torch.Tensor]:
        z = torch.zeros(b, self.hid, *hw, device=device)
        return z, z.clone()


class Seq2SeqConvLSTM(nn.Module):
    def __init__(self, n_phys: int = 7, n_time: int = 4, hidden: tuple[int, ...] = (32, 32), horizon: int = 3):
        super().__init__()
        self.n_phys, self.n_time, self.horizon = n_phys, n_time, horizon
        in_ch = n_phys + n_time + 1                                     # + 육지 마스크
        self.enc = nn.ModuleList([ConvLSTMCell(in_ch if i == 0 else hidden[i - 1], h) for i, h in enumerate(hidden)])
        self.dec = nn.ModuleList([ConvLSTMCell(in_ch if i == 0 else hidden[i - 1], h) for i, h in enumerate(hidden)])
        self.head = nn.Conv2d(hidden[-1], n_phys, 1)
        nn.init.zeros_(self.head.weight)                                # 처음에는 지속성 예보에서 출발한다
        nn.init.zeros_(self.head.bias)

    def _step(self, cells, x, states):
        out = x
        for i, cell in enumerate(cells):
            states[i] = cell(out, states[i])
            out = states[i][0]
        return out

    def forward(self, past: torch.Tensor, past_time: torch.Tensor, future_time: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """past (B,L,P,H,W), past_time (B,L,4), future_time (B,F,4), mask (B,1,H,W) → (B,F,P,H,W)"""
        b, L, _, H, W = past.shape
        dev = past.device
        spatial = lambda t: t[:, :, None, None].expand(-1, -1, H, W)  # noqa: E731
        states = [c.zeros(b, (H, W), dev) for c in self.enc]
        for t in range(L):
            x = torch.cat([past[:, t], spatial(past_time[:, t]), mask], dim=1)
            self._step(self.enc, x, states)
        dstates = [(h.clone(), c.clone()) for h, c in states]
        prev, outs = past[:, -1], []
        for j in range(self.horizon):
            x = torch.cat([prev, spatial(future_time[:, j]), mask], dim=1)
            top = self._step(self.dec, x, dstates)
            prev = prev + self.head(top)                                # 잔차
            outs.append(prev)
        return torch.stack(outs, dim=1)
