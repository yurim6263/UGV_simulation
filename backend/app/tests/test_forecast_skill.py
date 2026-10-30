"""
backend/app/tests/test_forecast_skill.py

예보 오차 분석(리드타임별 skill) 테스트. 작은 합성 parquet 으로 정답을 손으로 계산한다.
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.weather.forecast_skill import index_files, skill_by_lead

MODEL = datetime(2023, 6, 30, 22, 0)
CELLS = np.arange(6)


def write(path: Path, values: np.ndarray, cells=CELLS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"cell_id": cells, "normalized_c_total": values, "c_mob_prime": values, "c_sen_prime": values}).to_parquet(path)


def stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d_%H%M")


def build(tmp_path: Path, actual_by_lead: dict, forecast_by_lead: dict) -> Path:
    """lead(10분 단위) → 값 배열. 실황은 모델 시각부터, 예보는 모델 시각 폴더 안에 둔다."""
    for k, v in actual_by_lead.items():
        t = MODEL + timedelta(minutes=10 * k)
        write(tmp_path / "actual" / f"sim_cost_map_{stamp(t)}.parquet", v)
    for k, v in forecast_by_lead.items():
        t = MODEL + timedelta(minutes=10 * k)
        write(tmp_path / "forecast" / stamp(MODEL) / f"sim_cost_map_{stamp(t)}.parquet", v)
    return tmp_path


def test_files_are_indexed_by_issue_time_and_target_time(tmp_path):
    build(tmp_path, {0: np.zeros(6), 1: np.zeros(6)}, {0: np.zeros(6), 1: np.zeros(6)})
    actual, forecast = index_files(tmp_path)
    assert set(actual) == {MODEL, MODEL + timedelta(minutes=10)}
    assert set(forecast) == {MODEL} and set(forecast[MODEL]) == set(actual)


def test_skill_is_one_minus_the_error_ratio_to_persistence(tmp_path):
    base = np.full(6, 0.8)
    truth_10 = np.full(6, 0.7)                          # 실황은 0.8 → 0.7 (지속성 오차 0.1)
    build(tmp_path, {0: base, 1: truth_10}, {0: base, 1: np.full(6, 0.75)})   # 예보 0.75 (오차 0.05)
    row = {r["lead_min"]: r for r in skill_by_lead(tmp_path)["by_lead"]}[10]
    assert row["mae_persistence"] == pytest.approx(0.1) and row["mae_forecast"] == pytest.approx(0.05)
    assert row["skill"] == pytest.approx(0.5)           # 오차를 절반으로 줄였다
    assert row["bias_forecast"] == pytest.approx(0.05)  # 예보 − 실황


def test_a_forecast_worse_than_persistence_gets_negative_skill_and_negative_bias(tmp_path):
    """저장소의 실제 예보가 이렇다: 실황은 거의 그대로인데 예보는 위험을 낮게 본다."""
    base = np.full(6, 0.77)
    build(tmp_path, {0: base, 6: np.full(6, 0.75)}, {0: base, 6: np.full(6, 0.40)})
    result = skill_by_lead(tmp_path)
    row = {r["lead_min"]: r for r in result["by_lead"]}[60]
    assert row["skill"] < 0 and row["bias_forecast"] == pytest.approx(-0.35)
    assert result["share_leads_better_than_persistence"] == 0.0


def test_only_cells_present_in_forecast_actual_and_baseline_are_compared(tmp_path):
    """동적 파일은 경로 버퍼 안의 셀만 담는다. 한쪽에만 있는 셀을 0 으로 채워 비교하면 오차가 부풀려진다."""
    write(tmp_path / "actual" / f"sim_cost_map_{stamp(MODEL)}.parquet", np.full(6, 0.5))
    t1 = MODEL + timedelta(minutes=10)
    write(tmp_path / "actual" / f"sim_cost_map_{stamp(t1)}.parquet", np.full(4, 0.5), cells=np.arange(4))     # 셀 0~3 만
    write(tmp_path / "forecast" / stamp(MODEL) / f"sim_cost_map_{stamp(MODEL)}.parquet", np.full(6, 0.5))
    write(tmp_path / "forecast" / stamp(MODEL) / f"sim_cost_map_{stamp(t1)}.parquet", np.array([0.5, 0.5, 0.5, 0.5, 9.0, 9.0]))
    row = {r["lead_min"]: r for r in skill_by_lead(tmp_path)["by_lead"]}[10]
    assert row["mae_forecast"] == pytest.approx(0.0)    # 셀 4, 5 의 엉뚱한 값(9.0)은 비교에 들어가지 않는다


def test_missing_pairs_raise_instead_of_returning_an_empty_result(tmp_path):
    write(tmp_path / "actual" / f"sim_cost_map_{stamp(MODEL)}.parquet", np.zeros(6))
    (tmp_path / "forecast").mkdir()
    with pytest.raises(ValueError, match="비교할"):
        skill_by_lead(tmp_path)
