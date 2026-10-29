"""
backend/scripts/train_convlstm.py

Seq2Seq ConvLSTM 기상 예측 모델을 학습하고, 시험 구간(2022-07-01 이후)에서 지속성·기후값과 비교해 보고서를 쓴다.

    cd backend
    python scripts/train_convlstm.py [--epochs 16] [--hidden 32 32] [--threads 8] [--frac 0.25]

만드는 것(모두 backend/data/weather/ 아래):
  convlstm.pt              모델 가중치 + 표준화 통계 + 설정 (작아서 git 에 둔다)
  convlstm_metrics.json    시험 구간 지표와 기준선 대비 판정
  ../../../docs/weather_convlstm.md  위 지표로 쓴 보고서 (판정 문구는 숫자에서 자동으로 나온다)

원자료(ERA5-Land 2018~2022)가 필요하다: app/weather/dataset.py 설명 참고. 첫 실행은 자료를 읽느라 몇 분 걸린다.
Windows 에서 DataLoader 작업자를 쓰지 않으므로 별도 가드 외 주의할 것은 없다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from app.weather import weather_eval as ev  # noqa: E402
from app.weather.convlstm import Seq2SeqConvLSTM  # noqa: E402
from app.weather.dataset import CHANNELS, HORIZON, LOOKBACK, TRAIN_END, Normalizer, load_region_cached, time_features, window_starts  # noqa: E402

OUT = BACKEND / "data" / "weather"
DOC = BACKEND.parent / "docs" / "weather_convlstm.md"
VARS = ("rain", "t2m", "d2m", "wind", "swvl1", "fog")
UNIT = {"rain": "mm/h", "t2m": "K", "d2m": "K", "wind": "m/s", "swvl1": "m3/m3", "fog": "(0~1)"}
NAME = {"rain": "강수", "t2m": "기온", "d2m": "이슬점", "wind": "풍속", "swvl1": "토양수분", "fog": "안개 확률(파생, 팀 식)"}


class Batcher:
    def __init__(self, enc, tf, mask):
        self.enc, self.tf, self.mask = torch.from_numpy(enc), torch.from_numpy(tf), torch.from_numpy(mask.astype("float32"))[None, None]

    def get(self, starts: np.ndarray):
        idx = torch.as_tensor(starts)
        past = torch.stack([self.enc[s:s + LOOKBACK] for s in idx.tolist()])
        fut = torch.stack([self.enc[s + LOOKBACK:s + LOOKBACK + HORIZON] for s in idx.tolist()])
        pt = torch.stack([self.tf[s:s + LOOKBACK] for s in idx.tolist()])
        ft = torch.stack([self.tf[s + LOOKBACK:s + LOOKBACK + HORIZON] for s in idx.tolist()])
        return past, pt, ft, fut, self.mask.expand(len(idx), -1, -1, -1)


def masked_mse(pred, target, mask):
    m = mask[:, None]                                            # (B,1,1,H,W)
    return (((pred - target) ** 2) * m).sum() / (m.sum() * pred.shape[1] * pred.shape[2])


@torch.no_grad()
def predict(model, batcher, starts, bs=256):
    model.eval()
    out = []
    for i in range(0, len(starts), bs):
        past, pt, ft, _, mask = batcher.get(starts[i:i + bs])
        out.append(model(past, pt, ft, mask).numpy())
    return np.concatenate(out)


def evaluate(reg, norm, model, batcher, starts, train_hours):
    land = reg.land
    L, F = LOOKBACK, HORIZON
    truth_phys = np.stack([reg.data[s + L:s + L + F] for s in starts])               # (N,F,C,H,W)
    last_phys = np.stack([reg.data[s + L - 1] for s in starts])                      # (N,C,H,W)
    pred_phys = norm.decode(predict(model, batcher, starts))
    persist = np.repeat(last_phys[:, None], F, axis=1)
    # 기후값: 학습 구간의 (월, 시각)별 칸별 평균
    t = reg.times
    mon = (t.astype("datetime64[M]") - t.astype("datetime64[Y]")).astype(int)
    hr = (t - t.astype("datetime64[D]")).astype("timedelta64[h]").astype(int)
    clim = np.zeros((12, 24) + reg.data.shape[1:], dtype="float32")
    for m in range(12):
        for h in range(24):
            sel = (mon[:train_hours] == m) & (hr[:train_hours] == h)
            clim[m, h] = np.nanmean(reg.data[:train_hours][sel], axis=0)
    tt = np.stack([np.arange(s + L, s + L + F) for s in starts])
    climate = clim[mon[tt], hr[tt]]
    models = {"convlstm": pred_phys, "persistence": persist, "climatology": climate}
    rain_hist = np.stack([reg.data[s + L - 2:s + L, 0] for s in starts])                  # (N,2,H,W) 예측 직전 2시간의 관측 강수 (안개의 wet_3h 용)
    T = ev.derived(truth_phys, rain_hist)
    P = {k: ev.derived(v, rain_hist) for k, v in models.items()}
    errs = {k: ev.window_errors(P[k], T, land) for k in models}
    days = (t[starts + L - 1].astype("datetime64[D]") - np.datetime64("2018-01-01")).astype(int)
    res = {"n_windows": int(len(starts)), "land_cells": int(land.sum()), "metrics": {}, "vs_persistence": {}, "vs_climatology": {}}
    for k in models:
        res["metrics"][k] = {v: {"mae": errs[k][v]["mae"].mean(0).tolist(), "rmse": np.sqrt(errs[k][v]["mse"].mean(0)).tolist()} for v in VARS}
        res["metrics"][k]["rain_csi_0.1"] = ev.csi(P[k]["rain"], T["rain"], 0.1, land).tolist()
        res["metrics"][k]["rain_csi_1.0"] = ev.csi(P[k]["rain"], T["rain"], 1.0, land).tolist()
        res["metrics"][k]["fog_csi_0.5"] = ev.csi(P[k]["fog"], T["fog"], 0.5, land).tolist()
    for base, key in (("persistence", "vs_persistence"), ("climatology", "vs_climatology")):
        for v in VARS:
            rows = []
            for f in range(F):
                mean, lo, hi = ev.block_bootstrap_diff(errs["convlstm"][v]["mae"][:, f], errs[base][v]["mae"][:, f], days)
                rows.append({"hours": f + 1, "diff_mae": mean, "lo": lo, "hi": hi, "verdict": ev.verdict(lo, hi)})
            res[key][v] = rows
    return res


def render(res, cfg, hist, norm_info) -> str:
    m, lines = res["metrics"], []
    lines += ["# ConvLSTM 기상 예측 (직접 구현, 시험 구간 평가)", "",
              "> `backend/scripts/train_convlstm.py`가 자동으로 만든 문서다. 판정 문구는 숫자에서 나온다.", "",
              "## 무엇을 만들었나", "",
              "결과보고서의 최종 채택 구조(Seq2Seq, 인코더-디코더 ConvLSTM)를 PyTorch로 새로 구현했다 (`app/weather/convlstm.py`). **팀 원본 코드는 저장소에 없어서 층 수, 은닉 크기, 손실, 학습 설정은 우리가 정했고, 원본과 같다고 주장하지 않는다.**",
              f"- 입력 지난 {LOOKBACK}시간, 예측 이후 {HORIZON}시간. 채널: {', '.join(CHANNELS)} (+ 시각/연중일 sin·cos, 육지 마스크). 예측은 직전 프레임에 보정값을 더하는 잔차 구조라서 처음 상태가 지속성 예보다.",
              f"- 설정: 은닉 {cfg['hidden']}, 학습 {cfg['epochs_run']}에폭(최대 {cfg['epochs']}, 에폭마다 학습 창의 {cfg['frac']:.0%}를 무작위로 사용), 가장 좋은 검증 손실 {hist['best_val']:.4f} (에폭 {hist['best_epoch']}), 학습 시간 {hist['seconds']:.0f}초(CPU), 파라미터 {cfg['params']:,}개.",
              "- 자료: ERA5-Land 시간별 0.1°, 위도 53.9~54.9 x 경도 17.9~19.0 (10x11칸, 육지 78칸). 분할은 팀 분석과 같다: 학습 2018~2021, 검증 2022 상반기, **시험 2022-07-01 이후** (시나리오 2022-08-20 22시는 시험 구간).",
              "- 안개/시정은 ERA5-Land에 없다. 기온, 이슬점, 풍속, 최근 3시간 강수로 팀 노트북의 로지스틱 식(`app/weather/fog.py`)을 적용해 파생한다. 관측 시정 대비 검증이 아니라 ERA5 값으로 계산한 안개 확률을 맞힌 정도다. 최근 2시간 강수는 관측값을 쓰고 이후는 각 방법의 예측값을 쓴다.", "",
              f"## 시험 구간 결과 (창 {res['n_windows']:,}개, 육지 {res['land_cells']}칸)", "",
              "오차는 낮을수록 좋다. 판정은 일 단위 블록 부트스트랩(1,000회)으로 구한 `ConvLSTM − 기준선` MAE 차이의 95% 구간이다 (음수면 ConvLSTM 오차가 작다).", ""]
    for v in VARS:
        lines += [f"### {NAME[v]} ({UNIT[v]}) MAE", "", "| 예측 시간 | ConvLSTM | 지속성 | 기후값 | 지속성 대비 차이 (95% 구간) | 판정 | 기후값 대비 판정 |", "|---|---|---|---|---|---|---|"]
        for f in range(HORIZON):
            d, c = res["vs_persistence"][v][f], res["vs_climatology"][v][f]
            lines.append(f"| {f + 1}시간 | {m['convlstm'][v]['mae'][f]:.4f} | {m['persistence'][v]['mae'][f]:.4f} | {m['climatology'][v]['mae'][f]:.4f} | "
                         f"{d['diff_mae']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}] | {d['verdict']} | {c['verdict']} |")
        lines.append("")
    lines += ["### 사건 탐지 (CSI, 높을수록 좋음)", "", "| 지표 | 예측 시간 | ConvLSTM | 지속성 | 기후값 |", "|---|---|---|---|---|"]
    for key, label in (("rain_csi_0.1", "강수 ≥ 0.1 mm/h"), ("rain_csi_1.0", "강수 ≥ 1.0 mm/h"), ("fog_csi_0.5", "안개 확률 ≥ 0.5")):
        for f in range(HORIZON):
            lines.append(f"| {label} | {f + 1}시간 | {m['convlstm'][key][f]:.3f} | {m['persistence'][key][f]:.3f} | {m['climatology'][key][f]:.3f} |")
    allp = [x for v in VARS for x in res["vs_persistence"][v]]
    cnt = {k: sum(x["verdict"] == k for x in allp) for k in ("모델 우세(뚜렷)", "기준선 우세(뚜렷)", "단정 불가")}
    lines += ["", "## 요약", "",
              f"- 지속성 대비 (6개 변수 x 3개 예측 시간 = {len(allp)}칸 중): ConvLSTM 뚜렷하게 우세 **{cnt['모델 우세(뚜렷)']}**, 지속성 뚜렷하게 우세 **{cnt['기준선 우세(뚜렷)']}**, 단정 불가 **{cnt['단정 불가']}**.",
              "- 지속성 우세인 칸이 있으면 그대로 두고 적었다. 잔차 구조라서 \"지속성보다 나빠질 수 없다\"고 오해하기 쉬운데, 학습이 시험 구간에서 일반화하지 못하면 나빠질 수 있다.", "",
              "## 한계", "",
              "- 시험 구간이 2022년 하반기 6개월, 한 사례의 지역이다. 계절이 하나라는 뜻이고 다른 해에 같다고 말할 수 없다.",
              "- 격자가 10x11칸(약 11km)이라 공간 합성곱이 배울 이웃이 적다. 팀의 patch 실험(1x1 대 3x3)과 같은 한계다.",
              "- 평가는 ERA5-Land 재분석 값 대비다. 관측이나 실제 일기예보 대비가 아니다. 하이퍼파라미터는 거의 탐색하지 않았다 (검증 손실이 가장 낮은 에폭만 골랐다).",
              "- 강수는 log1p로 변환해 평균제곱오차로 학습했다. 강한 비(꼬리)는 평균 쪽으로 낮게 예측하는 경향이 있을 수 있다 (CSI@1.0을 같이 본다).",
              "- 위험도(LTWR) 예보 레이어는 이 모델의 예측값으로 만들 수 있지만, 모델이 지속성을 넘지 못한 변수는 위험도 예보의 정확도도 그만큼이다."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epochs", type=int, default=14)
    ap.add_argument("--hidden", type=int, nargs="+", default=[32, 32])
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--frac", type=float, default=0.25, help="에폭마다 학습 창에서 무작위로 뽑는 비율 (이웃 창은 거의 같아서 CPU 시간을 아끼려고 줄인다)")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rebuild-cache", action="store_true")
    ap.add_argument("--eval-only", action="store_true", help="학습 없이 저장된 convlstm.pt 로 평가와 보고서만 다시 만든다")
    args = ap.parse_args()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    reg = load_region_cached(args.rebuild_cache)
    train_hours = int(np.searchsorted(reg.times, TRAIN_END))
    norm = Normalizer.fit(reg.data, train_hours)
    enc = norm.encode(reg.data)
    batcher = Batcher(enc, time_features(reg.times), reg.land)
    tr, va, te = (window_starts(reg.times, w) for w in ("train", "val", "test"))
    print(f"창 수 학습 {len(tr)} 검증 {len(va)} 시험 {len(te)}  육지 {int(reg.land.sum())}칸", flush=True)

    if args.eval_only:
        ck = torch.load(OUT / "convlstm.pt", weights_only=False)
        cfg, hist = ck["config"], ck["history"]
        model = Seq2SeqConvLSTM(n_phys=len(CHANNELS), hidden=tuple(cfg["hidden"]), horizon=HORIZON)
        model.load_state_dict(ck["state"])
        res = evaluate(reg, norm, model, batcher, te, train_hours)
        res["config"], res["history"] = cfg, hist
        (OUT / "convlstm_metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        DOC.write_text(render(res, cfg, hist, norm.to_dict()), encoding="utf-8")
        print(f"평가만 다시 함: {DOC}")
        return
    model = Seq2SeqConvLSTM(n_phys=len(CHANNELS), hidden=tuple(args.hidden), horizon=HORIZON)
    params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=1)
    best, best_ep, bad, best_state, t0 = 1e9, 0, 0, None, time.time()
    for ep in range(1, args.epochs + 1):
        model.train()
        order = np.random.permutation(tr)[:max(args.batch, int(len(tr) * args.frac))]
        tot = n = 0
        for i in range(0, len(order), args.batch):
            past, pt, ft, fut, mask = batcher.get(order[i:i + args.batch])
            loss = masked_mse(model(past, pt, ft, mask), fut, mask)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(past)
            n += len(past)
        model.eval()
        with torch.no_grad():
            vl = vn = 0
            for i in range(0, len(va), 256):
                past, pt, ft, fut, mask = batcher.get(va[i:i + 256])
                vl += float(masked_mse(model(past, pt, ft, mask), fut, mask)) * len(past)
                vn += len(past)
        vl /= vn
        sched.step(vl)
        print(f"에폭 {ep:2d}  학습 {tot / n:.4f}  검증 {vl:.4f}  ({time.time() - t0:.0f}s)", flush=True)
        if vl < best - 1e-5:
            best, best_ep, bad = vl, ep, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= args.patience:
                print("검증 손실이 더 줄지 않아 중단", flush=True)
                break
    model.load_state_dict(best_state)
    hist = {"best_val": best, "best_epoch": best_ep, "seconds": time.time() - t0}
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = {"hidden": list(args.hidden), "frac": args.frac, "epochs": args.epochs, "epochs_run": ep, "params": params, "lookback": LOOKBACK, "horizon": HORIZON, "seed": args.seed}
    torch.save({"state": best_state, "normalizer": norm.to_dict(), "config": cfg, "history": hist}, OUT / "convlstm.pt")

    print("시험 구간 평가...", flush=True)
    res = evaluate(reg, norm, model, batcher, te, train_hours)
    res["config"], res["history"] = cfg, hist
    (OUT / "convlstm_metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    DOC.write_text(render(res, cfg, hist, norm.to_dict()), encoding="utf-8")
    print(f"저장: {OUT / 'convlstm.pt'}, {OUT / 'convlstm_metrics.json'}, {DOC}")


if __name__ == "__main__":
    main()
