# Five Weathers

> 기상·지형 위험이 시간에 따라 달라지는 환경에서 지휘관과 제대 통제관이 UGV(무인지상차량) 정찰 임무를 계획하고, 경로를 비교하며, 진행 상황을 공유하는 전술 의사결정 지원 프로토타입입니다.

Five Weathers는 단순한 지도 뷰어가 아닙니다. **임무 조건 입력 → 위험 기반 경로 계산 및 비교 → 임무 하달 → 제대별 운용 상황 확인**이라는 의사결정 흐름을 하나의 화면 체계로 보여줍니다.

현재 버전은 교육용·시연용 데이터와 일부 Mock 상태를 포함합니다. 실제 작전 체계가 아니라, 기상·지형 데이터와 UGV 운용 알고리즘을 결합했을 때 지휘관과 통제관에게 어떤 정보를 제공할 수 있는지 보여주는 프로토타입입니다.

## 무엇을 보여주는 프로젝트인가요?

- 지휘관이 UGV 수, 작전 시간, 성공률·손실률 기준, 제대별 목표 좌표와 정찰 시간을 입력합니다.
- 시스템이 기상·지형 위험 비용을 반영한 후보 경로와 임무 지표를 생성합니다.
- 지휘관은 균형·공격·신속 등 운용 관점에 따라 경로와 예상 효과를 비교합니다.
- 확정한 임무를 1~3제대 통제관에게 하달합니다.
- 지도, UGV 상태, 대기열, 임무 성공률, 자산 손실률, SOS 알림을 확인합니다.
- LTWR 지도에서 현재(T)와 미래(T+1~T+3)의 기상 위험 변화를 살펴봅니다.
- REST API와 WebSocket으로 임무 실행 상태와 대시보드 데이터를 전달합니다.

## 사용자 흐름

```text
지휘관 로그인
  → 임무·자산·제대별 목적지 입력
  → 시뮬레이션 및 후보 경로 확인
  → 운용 모드/경로 선택
  → 1~3제대에 임무 하달
  → 전체 제대 상황 모니터링

통제관 로그인
  → 자신에게 하달된 임무 브리핑 확인
  → 담당 제대의 UGV·경로·위험·알림 모니터링
```

통제관 화면은 같은 브라우저 세션에서 지휘관이 임무 입력과 시뮬레이션 준비를 마친 뒤 진입하도록 구성되어 있습니다.

## 로그인 계정

개발·시연용 기본 계정은 다음과 같습니다.

| 역할 | 담당 | 아이디 | 비밀번호 |
|---|---|---|---|
| 지휘관 | 전체 제대 | `admin` | `admin` |
| 통제관 | 1제대 | `user1` | `user1` |
| 통제관 | 2제대 | `user2` | `user2` |
| 통제관 | 3제대 | `user3` | `user3` |

> **계정:** 로그인은 항상 백엔드(DB 계정)로 인증합니다. 프론트엔드에는 더 이상 계정이나 비밀번호가 들어 있지 않으며, 백엔드가 꺼져 있으면 "서버에 연결할 수 없습니다"라고 표시됩니다. 최초 `admin` 계정의 비밀번호는 `backend/.env`의 `ADMIN_PASSWORD` 값이고, `user1`~`user3`은 백엔드 시작 시 위 표와 같은 비밀번호로 자동 생성됩니다(이미 있는 계정의 비밀번호는 덮어쓰지 않습니다).
>
> **동작:** 지휘관이 목표 3곳을 입력하고 "시뮬레이션 실행"을 누르면 서버가 임무를 만들고 균형/정밀/신속 3개 모드를 동시에 실행합니다(약 40초). 통제관은 지휘관이 실행을 끝낸 뒤에만 로그인할 수 있고, 서버가 자기 제대의 기록만 내려줍니다.

이 계정들은 시연 전용입니다. 외부에 배포할 때는 모든 비밀번호와 JWT 키를 반드시 변경해야 합니다.

## 주요 화면과 기능

### 지휘관

- 임무 기본값과 UGV 자산 수 입력
- 1~3제대의 목적지 좌표 및 정찰 시간 설정
- 경로별 성공률, 손실률, 거리, 예상 도착 시간 비교
- 종합·일사·기동성 위험 지도 확인
- 균형·공격·신속 운용 모드 비교 및 임무 하달
- 전체 제대 KPI, UGV 현황, 위험 대기열, SOS 알림 모니터링

### 통제관

- 담당 제대의 임무 브리핑 확인
- 배정된 UGV 수와 출발·도착 예정 시간 확인
- 담당 제대 경로와 위험 지도 확인
- UGV 상태 및 임무 진행 상황 모니터링

### 공통 데이터 표현

- 시계열 기상 위험 비용이 담긴 Parquet 지도 데이터
- T0~T3 LTWR HTML 지도
- 전술 경로 및 위험 오버레이 지도
- 시뮬레이션 결과 지도와 영상
- REST API 및 WebSocket 기반 상태 전달

## 기술 구성

| 영역 | 기술 |
|---|---|
| Frontend | React 19, JavaScript, Vite, CSS |
| Legacy Frontend | Solara, ipyleaflet, ipywidgets, Plotly |
| Backend | FastAPI, Pydantic, WebSocket, SlowAPI |
| Database | PostgreSQL 16, SQLAlchemy 2, Alembic, asyncpg |
| Data/Simulation | pandas, NumPy, SciPy, PyArrow, Pillow |
| Infrastructure | Docker, Docker Compose |

## 프로젝트 구조

```text
five_weathers/
├─ backend/
│  ├─ app/
│  │  ├─ api/             # 인증, 임무, 실행, 대시보드, 지도, WebSocket API
│  │  ├─ core/            # 환경설정, 로깅, rate limit, WebSocket 관리
│  │  ├─ db/              # 모델, 스키마, 세션, 초기 계정 생성
│  │  ├─ services/        # 인증·임무·경로·시뮬레이션 비즈니스 로직
│  │  └─ simulation/      # 알고리즘, 데이터 로더, 런타임, Mock/실행 러너
│  ├─ data/               # 위험 지도, LTWR 지도, 결과 영상
│  ├─ alembic/            # DB 마이그레이션
│  ├─ create_admin.py     # 지휘관 계정 생성·복구 도구
│  ├─ docker-compose.yml
│  └─ requirements.txt
├─ frontend_js/           # React + Vite 프론트엔드 (현재 사용)
│  ├─ src/                # App.jsx, data.js(시연용 기본 데이터), styles.css
│  ├─ static/             # 지도 HTML, 로그인 이미지 (Vite publicDir)
│  └─ package.json
├─ frontend_solara/       # 이전 Python/Solara 구현 (참고용)
├─ frontend_solara_ver2.0/ # Solara 수정본 (참고용)
├─ LICENSE
└─ README.md
```

## 로컬 실행

### 준비 사항

- Python 3.11 이상
- PostgreSQL 16 이상 또는 Docker Desktop
- 아래 명령은 PowerShell 기준

### 1. PostgreSQL과 백엔드 실행

가장 간단한 방법은 Docker Compose로 DB와 백엔드를 함께 실행하는 것입니다.

```powershell
cd backend
Copy-Item .env.example .env
```

`backend/.env`에서 최소한 다음 값을 실제 값으로 변경합니다.

```dotenv
JWT_SECRET_KEY=충분히_긴_임의의_문자열
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
```

```powershell
docker compose up -d --build
```

- Backend: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/health`
- Swagger API 문서: `http://127.0.0.1:8000/docs`

### 2. 백엔드를 Python으로 직접 실행하는 경우

PostgreSQL을 먼저 실행하고 `backend/.env`의 `DATABASE_URL`을 환경에 맞게 수정합니다.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8001
```

프론트엔드의 기본 API 주소가 `http://127.0.0.1:8001`이므로 직접 실행할 때는 8001 포트를 권장합니다. PostgreSQL 없이 시험하려면 `DATABASE_URL=sqlite+aiosqlite:///./demo.db`(개발용)로 실행할 수 있습니다. CORS는 `BACKEND_CORS_ORIGINS`에 `http://127.0.0.1:5173`을 포함해야 합니다. 8000 포트를 사용하려면 프론트 실행 전에 아래 환경변수를 지정하십시오.

### 3. React 프론트엔드 실행

새 PowerShell 창에서 실행합니다.

```powershell
cd frontend_js
Copy-Item .env.example .env
npm.cmd install
npm.cmd run dev
```

브라우저에서 `http://127.0.0.1:5173`으로 접속합니다. PowerShell 실행 정책상 `npm`이 차단되는 환경을 고려해 위 예시는 `npm.cmd`를 사용합니다.

기존 Solara 버전을 확인하려면 별도 터미널에서 다음과 같이 실행합니다.

```powershell
cd frontend_solara
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# requirements.txt의 solara 표기를 solara==1.40.0으로 수정한 후
pip install -r requirements.txt
solara run app.py
```

## 지도 재생 데이터

대시보드 지도는 HTML 파일이 아니라 **로그 데이터**를 읽어 그린다. 모드(균형/정밀/신속), 위험도 종류, 시간, 제대 필터, 이벤트 선택은 모두 지도 밖 패널에서 조작한다.

```text
이동 기록 CSV + 위험도 parquet
   └─ backend/scripts/export_replay.py
        └─ frontend_js/static/replay/{scenario,balance,explore,rush}.json, overlay/*/*.png
             └─ frontend_js/src/replay/  (useReplay 상태 → ReplayMap / ReplayControls / SidePanels)
```

데이터를 다시 만들려면 (경로는 환경에 맞게 변경):

```powershell
python backend/scripts/export_replay.py `
  --csv-dir  "<final_project>/html_code/enriched_csv_path" `
  --case-dir "<final_project>/html_code/15_Fog-driven_20230726_0300/15_Fog-driven_20230726_0300" `
  --out frontend_js/static/replay
```

재생 화면의 "데이터 출처"에서 두 가지를 볼 수 있습니다.

| 출처 | 만드는 법 | 설명 |
|---|---|---|
| 팀원 기록 | `export_replay.py` | 팀원 시뮬레이터가 만든 균형/정밀/신속 이동 기록 (참조) |
| 엔진 실행 | `backend/scripts/run_episode.py --out frontend_js/static/replay_engine --scale moderate --seed 1` | 이 저장소의 엔진(`algo/episode.py`)이 같은 시나리오를 직접 실행한 결과 |

서버에서 run을 실행하면 이동 기록이 `run_tracks`에 저장되고 `GET /api/runs/{id}/replay`가 같은 형식으로 돌려줍니다.
시뮬레이션 실행 환경변수: `SIM_WEATHER_SCALE`(clear | moderate | severe 또는 0~1, 기본 moderate), `SIM_TICK_SLEEP`(턴 사이 대기 초, 기본 0.5).

데이터 형식, 엔진 동작, 알려진 불일치는 [docs/data_contract.md](docs/data_contract.md)에 정리되어 있습니다.

## 전술 최적화 (NSGA-II + 몬테카를로)

균형/정밀/신속 모드의 편성과 전술 설정은 임의 값이 아니라 다목적 최적화 결과입니다.

```powershell
# 최적화 (개체 20 x 10세대) + 새 시드 몬테카를로 검증. 작업자 1개당 메모리 약 180MB. 약 40~70분
python backend/scripts/run_nsga2.py --pop 20 --gens 10 --val-seeds 10 --workers 6 --out backend/data/optimization/pareto.json
# 검증에서 실패했다면 최적화를 건너뛰고 이어서
python backend/scripts/run_nsga2.py --resume --val-seeds 10 --workers 6 --out backend/data/optimization/pareto.json
# 결과 보고서 생성 (docs/optimization_report.md)
python backend/scripts/make_report.py
```

- 목표: 수색 면적(최대화), 작전 시간(최소화), 운용자 과부하 시간(최소화). 제약: 평균 도착률 80% 이상.
- `backend/data/optimization/pareto.json`이 있으면 서버가 이 결과의 신속/정밀/균형 원형을 모드 설정으로 씁니다. `SIM_PRESETS=reference`로 팀원 기준 프리셋을 강제할 수 있습니다.
- 화면의 "최적화" 탭에서 파레토 곡선과 전술 메뉴판을 볼 수 있습니다(`frontend_js/static/optimization/pareto.json`).
- 결과 해석과 한계는 [docs/optimization_report.md](docs/optimization_report.md)에 있습니다. **대부분의 비교에서 95% 신뢰구간이 겹쳐 최적화의 이득을 단정할 수 없고**, 뚜렷한 차이는 날씨 무시 기준선 대비 수색 면적뿐입니다.

## 환경변수

`backend/.env.example`을 `backend/.env`로 복사한 뒤 사용합니다.

| 변수 | 설명 | 예시 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 비동기 연결 문자열 | `postgresql+asyncpg://postgres:password@localhost:5432/hanhwa` |
| `JWT_SECRET_KEY` | JWT 서명 키 | 충분히 긴 임의 문자열 |
| `ADMIN_USERNAME` | 최초 지휘관 계정 아이디 | `admin` |
| `ADMIN_PASSWORD` | 최초 지휘관 계정 비밀번호 | `admin` (시연용) |
| `JWT_ALGORITHM` | JWT 알고리즘 | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 액세스 토큰 만료 시간(분) | `60` |
| `BACKEND_CORS_ORIGINS` | 허용할 프론트엔드 Origin 목록 | `http://localhost:5173,http://127.0.0.1:5173` |
| `ASSET_BASE_PATH` | 지도·시뮬레이션 데이터 기준 경로 | `./data` |

React 프론트엔드는 다음 환경변수를 선택적으로 사용합니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_API_URL` | `http://127.0.0.1:8001` | REST API 주소 (`frontend_js/.env.example` 기준) |
| `VITE_WS_URL` | `ws://127.0.0.1:8001` | WebSocket 주소 (현재 `frontend_js`에서는 미사용) |

## DB와 계정 관리

백엔드 시작 시 개발 편의를 위해 테이블을 생성하고 기본 계정을 시드합니다. 운영 환경에서는 Alembic으로 스키마를 관리하는 것을 권장합니다.

```powershell
cd backend
alembic -c alembic/alembic.ini upgrade head
```

지휘관 계정을 새로 만들거나 비밀번호를 복구하려면 다음 명령을 사용합니다.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python create_admin.py --username admin --password admin --role commander
```

## 현재 구현 범위와 한계

- 저장소의 Parquet·HTML·MP4 데이터는 특정 시연 시나리오를 위한 샘플입니다.
- UI에는 백엔드 API 데이터와 프론트의 Mock/기본 상태가 함께 사용됩니다.
- 일부 화면 상태는 브라우저 프로세스 메모리에 있으므로 여러 사용자·브라우저 간에 완전히 공유되지 않을 수 있습니다.
- 실제 UGV 관제, 실시간 센서 수집, 군 운용 인증을 제공하는 운영 시스템은 아닙니다.
- 데모 계정과 기본 비밀번호는 개발 편의를 위한 것이므로 운영 환경에 그대로 사용하면 안 됩니다.

## 테스트

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

테스트는 PostgreSQL 없이 in-memory SQLite로 실행되므로 DB나 `.env`를 따로 준비할 필요가 없습니다(`app/tests/conftest.py`가 테스트용 환경변수를 지정합니다). 운영 DB는 PostgreSQL입니다.

## License

MIT License. 자세한 내용은 [LICENSE](LICENSE)를 확인하십시오.
