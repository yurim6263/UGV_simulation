"""
frontend/components/pareto_chart.py

파레토 곡선 시각화 컴포넌트.

시뮬레이션 결과(pareto_case A/B/C)를 scatter + 연결선으로 표시:
  X축: estimated_loss (손실률)
  Y축: success_probability (임무 성공률)
  색상: ltwr_status (GREEN/YELLOW/RED)
  레이블: pareto_case (A/B/C)

plotly를 사용해 인터랙티브 차트 렌더링.
"""

import solara
import plotly.graph_objects as go

import state

# ltwr_status → 색상
LTWR_COLORS = {
    "GREEN":  "#2ecc71",
    "YELLOW": "#f1c40f",
    "RED":    "#e74c3c",
}


@solara.component
def ParetoChart():
    """파레토 곡선 차트."""
    results = solara.use_state_reactive(state.simulation_results)

    if not results.value:
        with solara.Card(style={"padding": "24px", "textAlign": "center"}):
            solara.Text("시뮬레이션 결과 없음", style={"color": "#888"})
        return

    # pareto_case A/B/C 순으로 정렬
    sorted_results = sorted(results.value, key=lambda r: r.get("pareto_case", ""))

    x_vals = [r.get("estimated_loss", 0) for r in sorted_results]
    y_vals = [r.get("success_probability", 0) for r in sorted_results]
    labels = [r.get("pareto_case", "?") for r in sorted_results]
    ltwr   = [r.get("ltwr_status", "GREEN") for r in sorted_results]
    colors = [LTWR_COLORS.get(s, "#aaa") for s in ltwr]
    saved  = [r.get("personnel_saved", 0) for r in sorted_results]
    minute = [r.get("minute", 0) for r in sorted_results]

    hover_text = [
        f"케이스: {labels[i]}<br>"
        f"성공률: {y_vals[i]:.1%}<br>"
        f"손실율: {x_vals[i]:.3f}<br>"
        f"생존 인원: {saved[i]}명<br>"
        f"소요 시간: {minute[i]}분<br>"
        f"LTWR: {ltwr[i]}"
        for i in range(len(sorted_results))
    ]

    fig = go.Figure()

    # 연결선 (파레토 프론티어)
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_vals,
        mode="lines",
        line=dict(color="#cccccc", width=1, dash="dash"),
        showlegend=False,
        hoverinfo="skip",
    ))

    # 각 케이스 점
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        mode="markers+text",
        marker=dict(size=18, color=colors, line=dict(width=2, color="white")),
        text=labels,
        textposition="top center",
        textfont=dict(size=13, color="white"),
        hovertext=hover_text,
        hoverinfo="text",
        showlegend=False,
    ))

    # LTWR 범례용 더미 트레이스
    for status, color in LTWR_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(size=12, color=color),
            name=f"LTWR: {status}",
            showlegend=True,
        ))

    fig.update_layout(
        title="파레토 최적 경로 곡선",
        xaxis_title="추정 손실률 (낮을수록 좋음)",
        yaxis_title="임무 성공 확률 (높을수록 좋음)",
        xaxis=dict(range=[0, max(x_vals) * 1.2 if x_vals else 1], tickformat=".3f"),
        yaxis=dict(range=[0, 1.05], tickformat=".0%"),
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(color="white"),
        legend=dict(x=0.01, y=0.01, bgcolor="rgba(0,0,0,0.4)"),
        margin=dict(l=60, r=20, t=50, b=60),
        height=380,
    )

    solara.display(fig)

    # 케이스 상세 카드
    with solara.Row():
        for r in sorted_results:
            case = r.get("pareto_case", "?")
            ltwr_s = r.get("ltwr_status", "GREEN")
            color = LTWR_COLORS.get(ltwr_s, "#aaa")
            with solara.Card(style={"minWidth": "160px", "borderTop": f"4px solid {color}"}):
                solara.Text(f"케이스 {case}", style={"fontWeight": "bold", "fontSize": "1.1rem"})
                solara.Text(f"성공률: {r.get('success_probability', 0):.1%}")
                solara.Text(f"생존 인원: {r.get('personnel_saved', 0)}명")
                solara.Text(f"소요: {r.get('minute', 0)}분")
                solara.Text(f"LTWR: {ltwr_s}", style={"color": color, "fontWeight": "bold"})
