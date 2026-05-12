# Five Weathers UGV Tactical Decision Support System

전술 UGV 운용을 위한 실시간 의사결정 지원 시스템입니다.  
본 프로젝트는 임무 변수 입력, 경로 계획 비교, 실시간 상황 시각화를 통해 전술적 의사결정을 지원하는 대시보드 형태로 구현되었습니다.

백엔드는 **FastAPI**, 프론트엔드는 **Solara** 기반으로 구성되어 있으며, 현재는 **Mock 기반 시뮬레이션 환경**을 중심으로 동작합니다.

---

## Overview
> 국방 데이터 분석 교육 과정의 최종 프로젝트로 수행한 UGV 전술 의사결정 지원 시스템입니다.

Five Weathers는 전술 환경에서 UGV 운용 판단을 지원하기 위한 프로토타입 시스템입니다.

주요 목표는 다음과 같습니다.

- 임무 조건 기반 시뮬레이션 실행
- 복수 경로안 비교 및 선택 지원
- 실시간 주요 운용 지표(KPI) 및 상태 정보 시각화
- UI / API / 시뮬레이션 흐름 통합 검증
- 향후 실제 알고리즘 연동을 고려한 구조 설계

---

## Tech Stack

### Backend
- FastAPI
- SQLAlchemy
- PostgreSQL
- Alembic
- Pydantic
- WebSocket

### Frontend
- Solara
- ipywidgets
- ipyleaflet
- Starlette
- websocket-client

### Infra / Tools
- Docker
- GitHub
- Python 3.11+

---

## Project Structure

```bash
FIVE_WEATHERS/
├── backend/
│   ├── alembic/                # DB 마이그레이션 관리
│   ├── app/
│   │   ├── api/                # REST / WebSocket 엔드포인트
│   │   ├── core/               # 설정, 보안, 로깅, WS 관리
│   │   ├── db/                 # DB 모델, 스키마, 세션
│   │   ├── services/           # 비즈니스 로직
│   │   └── simulation/         # 시뮬레이션 관련 모듈
│   ├── data/                   # 시드/실험용 데이터
│   ├── .env.example            # 환경변수 예시
│   ├── create_admin.py         # 관리자 계정 복구 스크립트
│   ├── docker-compose.yml      # 백엔드 + DB 실행 구성
│   ├── Dockerfile              # 백엔드 컨테이너 이미지 정의
│   └── requirements.txt
│
├── frontend/
│   ├── __pycache__/
│   ├── components/             # UI 컴포넌트
│   ├── public/                 # 프론트엔드 공개 정적 리소스
│   ├── services/               # API 연동 / 상태 처리
│   ├── static/                 # 정적 시각화 파일
│   ├── api_client.py           # API 클라이언트
│   ├── app.py                  # Solara 메인 진입점
│   ├── requirements.txt
│   └── state.py                # 전역 상태 관리
│
├── public/                     # 루트 공개 리소스
├── .gitignore
├── LICENSE
└── README.md
```

---

## Main Features

### 1. 로그인 페이지
- 계정을 **지휘관 / 통제관 1~3**으로 구분하여 로그인할 수 있습니다.
- 계정 역할에 따라 접속 후 표시되는 페이지와 확인 가능한 정보가 다르게 구성됩니다.

### 2. 지휘관 임무 변수 입력 페이지
- 지휘관은 도착지 1~3에 대한 **위도 / 경도 정보**를 입력할 수 있습니다.
- 입력된 임무 변수는 이후 경로 계획 및 임무 모드별 운용 정보 생성에 반영됩니다.

### 3. 지휘관 통합 운용 페이지
- **임무 모드(균형 / 정밀 / 신속)** 별 경로맵을 시각화합니다.
- 경로맵은 **종합 위험도 맵, 센서 위험도 맵, 기동성 위험도 맵**으로 구분하여 확인할 수 있습니다.
- **이벤트 알림(SOS 요청)** 을 확인할 수 있으며, 각 UGV와 통제관의 현재 타일 상황 정보도 함께 제공합니다.
- 임무 모드별로 각 제대의 **운용 UGV 수, 도착지 정보, 출발 예정 시각, 도착 예정 시각**을 확인할 수 있습니다.
- 부대 전체 기준으로 **임무 성공률, 최저 성공률, 도착 UGV 수, SOS 요청 건수, 건당 대기열, 통제관 가동률** 정보를 제공합니다.
- **지상작전 기상 위험도(LTWR)** 의 1시간 후, 2시간 후, 3시간 후 예측 맵을 제공합니다.
- 통제관에게 임무를 하달하는 버튼을 통해, 선택한 임무 모드에 따른 데이터를 전달할 수 있습니다.

### 4. 통제관 임무 브리핑 및 자산 확인 페이지
- 각 제대별로 하달받은 임무 데이터를 확인할 수 있습니다.
- 부대 기본 자산 현황과 각 제대의 자산 현황, 임무 관련 정보를 브리핑 형태로 제공합니다.

### 5. 통제관 실시간 운용 페이지
- 하달받은 **임무 모드(균형 / 정밀 / 신속)** 기준으로 경로맵을 시각화합니다.
- 경로맵은 **종합 위험도 맵, 센서 위험도 맵, 기동성 위험도 맵**으로 나누어 확인할 수 있습니다.
- **이벤트 알림(SOS 요청)** 과 각 UGV 및 통제관의 현재 타일 상황 정보를 확인할 수 있습니다.
- 각 제대별 **운용 UGV 수, 도착지 정보, 출발 예정 시각, 도착 예정 시각**을 제공합니다.
- 부대 전체 기준으로 **임무 성공률, 최저 성공률, 도착 UGV 수, SOS 요청 건수, 건당 대기열, 통제관 가동률** 정보를 제공합니다.
- **지상작전 기상 위험도(LTWR)** 의 1시간 후, 2시간 후, 3시간 후 예측 맵을 제공합니다.
- 하달된 임무를 확인하는 기능을 제공합니다.

---

## Current Mode

현재 프로젝트는 **Mock 기반 시뮬레이션 모드**를 중심으로 동작합니다.

- 더미 데이터 기반으로 전체 UI / API 흐름을 검증할 수 있습니다.
- 실제 알고리즘 연동 전 단계에서 통합 테스트 및 화면 검증이 가능합니다.
- 향후 실제 알고리즘은 `backend/app/simulation/` 하위 구조에 맞춰 확장 연동할 수 있도록 설계되었습니다.

즉, 현재 버전은 **실제 알고리즘 연동 전 단계의 전술 지원 프로토타입으로, 모의 데이터를 기반으로 전체 시스템 흐름을 검증**하는 데 초점을 두고 있습니다.

---

## Run Locally

### Prerequisites
- Python 3.11+
- PostgreSQL 16+
- Git
- Docker

---

### 1. Backend 실행

```bash
cd backend

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
```

이후 `.env` 파일을 열어 실제 환경값을 입력합니다.

백엔드 서버 실행:

```bash
uvicorn app.main:app --reload
```

- Backend: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

---

### 2. Frontend 실행

```bash
cd frontend

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

solara run app.py
```

- Frontend: `http://localhost:8765`

---

## Environment Variables

`backend/.env.example` 파일을 `backend/.env`로 복사한 뒤 아래 항목들을 설정합니다.

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | `postgresql+asyncpg://postgres:pass@localhost:5432/fiveweathersDB` |
| `JWT_SECRET_KEY` | JWT 서명 키 | 충분히 긴 랜덤 문자열 |
| `ADMIN_USERNAME` | 초기 관리자 계정 | `user1` |
| `ADMIN_PASSWORD` | 초기 관리자 비밀번호 | `user1` |

---

## Database Migration

Alembic 기반 DB 마이그레이션을 사용하는 경우 예시는 다음과 같습니다.

```bash
cd backend
alembic upgrade head
```

DB 스키마 변경 시 Alembic 마이그레이션을 통해 반영할 수 있습니다.

---

## Admin Recovery

관리자 계정 생성이 정상적으로 되지 않았을 경우 아래 명령으로 계정을 수동 생성할 수 있습니다.

```bash
cd backend
.venv\Scripts\activate
python create_admin.py --username user1 --password user1
```

---

## Docker

백엔드 및 데이터베이스를 Docker 기반으로 실행하려면:

```bash
cd backend
docker compose up -d
```

필요 시 `Dockerfile`과 `docker-compose.yml`을 기준으로 백엔드 컨테이너 환경을 구성할 수 있습니다.

---

## Workflow

본 시스템은 다음 흐름으로 사용됩니다.

1. 로그인
2. 지휘관의 임무 변수 입력
3. 지휘관의 경로 비교 및 선택
4. 지휘관->통제관으로 임무 하달
5. 통제관의 임무 정보 및 경로 확인

이 흐름을 통해 사용자는 임무 준비 단계부터 실시간 모니터링 단계까지 하나의 인터페이스에서 확인할 수 있습니다.

---

## Notes

- 본 프로젝트는 전술 UGV 운용 지원을 위한 프로토타입 시스템입니다.
- 현재 일부 기능은 Mock 데이터 기반으로 동작합니다.
- 실제 알고리즘 및 고도화된 의사결정 로직은 추후 확장 가능한 구조로 분리 설계되어 있습니다.
- 저장소 구조는 개발 진행에 따라 지속적으로 업데이트될 수 있습니다.

---

## My Role

- FastAPI 백엔드 구조 설계 및 API 구성
- Solara 프론트엔드 UI 구성
- 상태 시각화 및 대시보드 흐름 설계
- Mock 데이터 기반 시뮬레이션 통합 환경 구성
- UGV 전술 지원 시나리오 기반 기능 구현

---

## License

MIT License