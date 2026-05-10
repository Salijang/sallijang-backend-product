# sallijang-backend-product

상품 및 가게 관리 서비스입니다.

## 기술 스택

- **Python 3.11** / FastAPI
- **PostgreSQL** (asyncpg, SQLAlchemy, Alembic)
- **Redis** (상품 재고 캐싱)
- **AWS SQS** (재고 차감 이벤트 비동기 처리)
- **AWS S3** (상품 이미지 저장)
- **AWS Bedrock Claude** (상품 이미지 AI 분석)
- **Kakao Map API** (가게 주소 지오코딩)

## 주요 기능

- 가게 등록 / 조회 / 수정 (Kakao API로 좌표 자동 변환)
- 상품 등록 / 조회 / 수정 / 삭제 (소프트 삭제)
- 위치 기반 상품 검색 (Haversine 거리 계산)
- 상품 이미지 S3 업로드 (Presigned URL)
- AWS Bedrock Claude로 이미지에서 상품명·설명·카테고리 자동 생성
- 리뷰 작성 / 조회 / 삭제 (가게 평균 평점 자동 업데이트)
- Saga 패턴: SQS로 재고 차감 요청 수신 및 결과 발행

## API 엔드포인트

### 가게

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/stores/` | 가게 생성 |
| GET | `/api/v1/stores/` | 가게 목록 조회 |
| GET | `/api/v1/stores/{store_id}` | 가게 상세 조회 |
| PATCH | `/api/v1/stores/{store_id}` | 가게 정보 수정 |

### 상품

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/products/` | 상품 생성 |
| GET | `/api/v1/products/` | 상품 목록 조회 (위치 기반) |
| GET | `/api/v1/products/{product_id}` | 상품 상세 조회 |
| PATCH | `/api/v1/products/{product_id}` | 상품 수정 |
| PATCH | `/api/v1/products/{product_id}/remaining` | 재고 수량 조정 |
| DELETE | `/api/v1/products/{product_id}` | 상품 삭제 |
| GET | `/api/v1/products/upload-url` | S3 Presigned URL 발급 |
| POST | `/api/v1/products/analyze-image` | 이미지 AI 분석 |

### 리뷰

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/reviews/` | 리뷰 작성 |
| GET | `/api/v1/reviews/` | 리뷰 목록 조회 |
| DELETE | `/api/v1/reviews/{review_id}` | 리뷰 삭제 |

## 환경 변수

| 변수명 | 설명 |
|--------|------|
| `DB_HOST` | PostgreSQL 호스트 |
| `DB_PORT` | PostgreSQL 포트 (기본값: 5432) |
| `DB_USER` | DB 사용자명 |
| `DB_NAME` | DB 이름 |
| `DB_PASSWORD` | DB 비밀번호 (미설정 시 RDS IAM 인증) |
| `AWS_REGION` | AWS 리전 (기본값: ap-northeast-2) |
| `SQS_QUEUE_URL` | SQS 큐 URL |
| `REDIS_URL` | Redis 연결 URL |
| `IMAGE_BUCKET_NAME` | S3 이미지 버킷명 |
| `CDN_URL` | CDN URL |
| `KAKAO_REST_API_KEY` | Kakao Map REST API 키 |
| `NOTIFY_SERVICE_URL` | Notify 서비스 URL |
| `SECRET_KEY` | JWT 서명 키 |

## 로컬 실행

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

## Docker

```bash
docker build -t sallijang-product .
docker run -p 8001:8001 \
  -e DB_HOST=<host> \
  -e DB_USER=<user> \
  -e DB_PASSWORD=<password> \
  -e REDIS_URL=redis://redis:6379 \
  -e KAKAO_REST_API_KEY=<key> \
  -e IMAGE_BUCKET_NAME=<bucket> \
  -e SECRET_KEY=<secret> \
  sallijang-product
```
