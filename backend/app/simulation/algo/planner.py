"""
backend/app/simulation/algo/planner.py

시간 의존 경로 탐색 (Time-dependent shortest path).

기존 PathFinder3D 는 "이동 1칸 = 시간 레이어 1개(10분)"로 가정해, 18개 레이어로는 17칸(3.4km)까지만
계획할 수 있었다. 실제로는 한 턴(10분)에 AP 1,000,000 으로 약 7~10칸을 이동한다.

여기서는 시간을 AP 누적량으로 센다:
    그 칸에 도착하는 시점 = 경로를 따라 지금까지 쓴 AP 의 합
    참조 레이어 k       = floor(도착 시점 AP / 턴당 AP)
간선 비용이 도착 시점에 따라 달라지므로, 정적 격자 그래프 위에서
  1) 모든 노드의 참조 레이어를 0 으로 두고 Dijkstra
  2) 얻은 경로의 AP 누적량으로 노드별 참조 레이어를 다시 계산
  3) 레이어 배정이 더 바뀌지 않을 때까지 반복(보통 2~3회)
하는 고정점 반복으로 근사한다. 날씨가 천천히 변하는 경우(FIFO 성질) 정확하며, 벡터 연산만 쓴다.

비용 = AP(도착 칸의 위험도) × 지형 계수 × (1 + 페널티)   ← 경로 선택 기준
시간 = AP                                                 ← 경로를 따라 누적, 참조 레이어 결정
통행 불가 지형과 데이터 없음(NaN) 셀은 간선 자체를 제거한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from app.simulation.algo.ap_resolver import AP_TURN, DIAGONAL_COEFF, ap_orthogonal

_MOVES = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


@dataclass
class Plan:
    cells: list[tuple[int, int]]   # 출발 셀을 포함한 경로 [(row, col), ...]. 도달 불가면 빈 리스트
    est_ap: float                  # 예상 AP 소요 (계획 레이어 기준)

    @property
    def reachable(self) -> bool:
        return bool(self.cells)


class GridPlanner:
    def __init__(self, ny: int, nx: int, terrain_mult: np.ndarray, blocked: np.ndarray, nt: int):
        self.ny, self.nx, self.nt = ny, nx, nt
        self.n = ny * nx
        self.terrain = terrain_mult.astype(np.float64).ravel()
        self.blocked = blocked.ravel()

        # 정적 간선 구조 (한 번만 만든다)
        rows, cols = np.divmod(np.arange(self.n), nx)
        us, vs, diag = [], [], []
        for dy, dx in _MOVES:
            nr, nc = rows + dy, cols + dx
            ok = (nr >= 0) & (nr < ny) & (nc >= 0) & (nc < nx)
            us.append(np.arange(self.n)[ok])
            vs.append((nr * nx + nc)[ok])
            diag.append(np.full(ok.sum(), dy != 0 and dx != 0))
        self._u = np.concatenate(us)
        self._v = np.concatenate(vs)
        self._diag = np.concatenate(diag)
        self._edge_factor = np.where(self._diag, DIAGONAL_COEFF, 1.0)
        self._cell_rc = np.stack([rows, cols], axis=1)

    def ap_cube(self, mob_cube: np.ndarray, sen_cube: np.ndarray, sensitivity: float = 1.0) -> np.ndarray:
        """계획 레이어(NT, ny, nx)의 직선 이동 AP. 위험도를 sensitivity 배로 본다. 데이터 없음은 inf."""
        scale = float(sensitivity)
        ap = ap_orthogonal(np.clip(mob_cube * scale, 0, 1), np.clip(sen_cube * scale, 0, 1))
        return np.where(np.isfinite(mob_cube) & np.isfinite(sen_cube), ap, np.inf).reshape(self.nt, self.n)

    def plan(
        self,
        ap_cube: np.ndarray,
        start: tuple[int, int],
        goal: tuple[int, int],
        penalty: np.ndarray | None = None,
        start_ap_used: float = 0.0,
        max_iter: int = 4,
    ) -> Plan:
        s = start[0] * self.nx + start[1]
        g = goal[0] * self.nx + goal[1]
        if s == g:
            return Plan([tuple(start)], 0.0)
        if self.blocked[g]:
            return Plan([], float("inf"))

        pen = np.ones(self.n) if penalty is None else 1.0 + penalty.ravel()
        k_node = np.zeros(self.n, dtype=np.int64)   # 노드별 참조 레이어
        best: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None

        for _ in range(max_iter):
            ap_node = ap_cube[k_node, np.arange(self.n)]               # 노드 v 에 직선 진입하는 AP
            node_cost = ap_node * self.terrain * pen
            node_cost[self.blocked] = np.inf
            cost = node_cost[self._v] * self._edge_factor
            keep = np.isfinite(cost)
            graph = csr_matrix((cost[keep], (self._u[keep], self._v[keep])), shape=(self.n, self.n))
            dist, pred = dijkstra(graph, directed=True, indices=s, return_predecessors=True)
            best = (dist, pred, ap_node)
            if not np.isfinite(dist[g]):
                return Plan([], float("inf"))

            # 경로를 따라 AP 누적 → 노드별 도착 시점 → 참조 레이어
            tap = np.zeros(self.n)
            order = np.argsort(dist)
            reach = order[np.isfinite(dist[order])][1:]
            rc = self._cell_rc
            for v in reach:
                p = pred[v]
                diag = rc[p, 0] != rc[v, 0] and rc[p, 1] != rc[v, 1]
                tap[v] = tap[p] + ap_node[v] * (DIAGONAL_COEFF if diag else 1.0)
            new_k = np.minimum(((tap + start_ap_used) // AP_TURN).astype(np.int64), self.nt - 1)
            if np.array_equal(new_k, k_node):
                break
            k_node = new_k

        dist, pred, ap_node = best
        path = [g]
        while path[-1] != s:
            path.append(int(pred[path[-1]]))
        path.reverse()
        cells = [(int(self._cell_rc[i, 0]), int(self._cell_rc[i, 1])) for i in path]
        est = 0.0
        for a, b in zip(path[:-1], path[1:]):
            diag = self._cell_rc[a, 0] != self._cell_rc[b, 0] and self._cell_rc[a, 1] != self._cell_rc[b, 1]
            est += ap_node[b] * (DIAGONAL_COEFF if diag else 1.0)
        return Plan(cells, float(est))
