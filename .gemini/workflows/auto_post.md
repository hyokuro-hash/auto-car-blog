# Workflow: Auto Car Blog - AI 자동 발행 및 브리핑 파이프라인

본 워크플로우는 **[해외 자동차 뉴스 & 오너 커뮤니티 데이터 자동 수집 -> AI 심층 분석 -> 다중 플랫폼 자동 포스팅 -> 텔레그램 알림]** 파이프라인을 실행하고 모니터링하기 위한 안티그래비티 전용 가이드입니다.

---

## 1. 사전 체크리스트
파이프라인을 실행하기 전, 다음 항목들을 설정해야 합니다.

1. **`.env` 파일 생성**: 프로젝트 루트 폴더에 `.env` 파일을 복사 및 생성하고 필요한 토큰 값을 기입합니다.
   ```bash
   cp .env.example .env
   ```
2. **의존성 패키지 설치**:
   ```bash
   pip install -r requirements.txt
   ```
3. **가상 환경 구성 (권장)**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate   # Windows
   ```

---

## 2. 파이프라인 작동 시나리오

### 시나리오 A: 로컬 실행 모드 (수동/정기 브리핑)
로컬 PC에서 텔레그램 봇 폴링 및 APScheduler(매일 오전 08:00)를 통합 실행합니다.

```bash
# RUN_MODE=local 상태로 실행
python main.py
```
- **텔레그램 대화방**에서 `/news [차종/키워드]` 명령을 전달하여 수동 수집 및 포스팅 승인 프로세스를 진행합니다.
- 콘솔에 노출되는 로그를 확인하여 Jina Reader 스크래핑 오류 및 Gemini API 할당량 초과 여부를 관측합니다.

### 시나리오 B: Vercel Serverless 배포 모드
Vercel에 코드를 배포한 뒤 웹훅 및 외부 크론 스케줄링을 통해 동작시킵니다.

1. **텔레그램 봇 웹훅 등록**:
   ```bash
   # 브라우저 혹은 curl을 이용해 텔레그램 API에 웹훅 등록
   https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<YOUR-VERCEL-DOMAIN>/api/webhook
   ```
2. **일일 크론 트리거**:
   - `vercel.json` 설정 파일 또는 외부 Cron Job 서비스(UptimeRobot 등)를 이용해 매일 특정 시간에 `https://<YOUR-VERCEL-DOMAIN>/api/cron` 엔드포인트를 GET 호출합니다.

---

## 3. 핵심 모듈별 트러블슈팅

### 1) Jina Reader 스크래핑 실패
- Jina Reader (`https://r.jina.ai/`)는 별도의 API key가 없어도 동작하나, 트래픽 폭주 시 응답 속도가 저하되거나 차단될 수 있습니다.
- 스크래퍼가 빈 본문을 반환할 경우, `collector.py`에서 oEmbed 또는 기본 RSS 요약본만을 바탕으로 Gemini 작성을 시도하게끔 폴백 설계되어 있습니다.

### 2) YouTube 자막 추출 오류
- `youtube-transcript-api`는 영상에 자막 데이터가 비활성화되었을 시 예외를 발생시킵니다.
- 이 경우 `collector.py`는 자동으로 해당 영상의 HTML 메타 정보(`og:description`)를 수집하는 폴백 메커니즘을 가동합니다.

### 3) DB 캐싱 중복 방지 동작 확인
- Firebase나 Google Sheets API 크레덴셜이 연결되지 않은 경우, 로컬 디렉토리에 `cache.json` 및 `drafts_cache.json`을 자동 생성하여 로컬 메모리 캐시 형태로 테스트가 가동되도록 보장합니다.
