# Promotion Winner Batch

MySQL 참여 데이터를 정제해 참여 유저 중 랜덤 당첨자 1명을 추첨하고, Notion 운영 데이터베이스에 공고문 티켓을 생성하는 Python 배치입니다.

## Setup

```bash
pip install -r requirements.txt
```

환경변수는 `.env`에 등록합니다.

## Run

생성될 공고문만 확인:

```bash
python event.py --dry-run
```

MySQL 없이 코드에 포함된 샘플 데이터로 확인:

```bash
python event.py --mock-data --dry-run
```

Notion에 실제 티켓 생성:

```bash
python event.py
```

Notion에서 `AI 검수 상태 = 검수 요청`인 페이지를 찾아 기준 노션 페이지 글과 비교하고, Gemini로 세계관 오류 여부를 판단해 Notion에 반영:

```bash
python ai_compliance_listener.py
```

한 번만 확인하고 종료:

```bash
python ai_compliance_listener.py --once
```

로컬 MySQL에 샘플 DB와 테이블을 만들려면:

```bash
mysql -u root -p < seed_demo.sql
```

## 세계관 검사 코드

`ai_compliance_listener.py`는 Notion 운영 데이터베이스에서 `AI 검수 상태`가 `검수 요청`인 페이지를 찾아 세계관 정합성을 자동 검수하는 리스너입니다.

처리 흐름은 아래와 같습니다.

1. Notion 데이터베이스에서 `검수 요청` 상태의 페이지를 조회합니다.
2. 대상 페이지 본문 텍스트를 가져옵니다.
3. 페이지의 `세계관 참고 페이지` 속성 또는 `.env`의 `NOTION_REFERENCE_PAGE_ID`로 기준 노션 페이지를 찾습니다.
4. 기준 페이지 글과 검수 대상 글을 Gemini에 함께 전달합니다.
5. Gemini 응답의 `lore_pass`, `brand_pass`, `lore_reason`, `alternative_text`를 바탕으로 Notion 속성과 본문을 업데이트합니다.

검수 기준은 크게 두 가지입니다.

- `세계관 정합성 체크`: 기준 노션 페이지의 설정/서사와 충돌하지 않는지 확인합니다.
- `브랜드 가이드 준수 여부 체크`: 공지나 운영 문서로 사용하기에 문체가 부적절하지 않은지 확인합니다.

검수가 끝나면 `AI 검수 상태`를 `검수 완료`로 바꾸고, 페이지 본문에 `AI 검수 결과` 블록을 추가합니다. 이미 `AI 검수 결과` 제목 블록이 있는 페이지에는 중복 결과를 추가하지 않습니다.

리스너를 계속 실행하려면:

```bash
python ai_compliance_listener.py
```

한 번만 검사하고 종료하려면:

```bash
python ai_compliance_listener.py --once
```

## Required MySQL Table

```sql
SELECT user_id, nickname, content, user_ip
FROM promotion_participants;
```

Notion 데이터베이스에는 아래 속성이 있어야 합니다.

- `작업명`: title
- `업무 단계`: select, `4단계 운영` 옵션 포함
- `진행 상황`: status, `검수 요청` 옵션 포함

AI 검수 리스너용 Notion 데이터베이스에는 아래 속성이 필요합니다.

- `AI 검수 상태`: select 또는 status, `검수 요청` 옵션 포함
- `세계관 참고 페이지`: url 또는 rich_text, 선택. 없으면 `.env`의 `NOTION_REFERENCE_PAGE_ID` 사용
- `세계관 정합성 체크`: checkbox, 선택
- `브랜드 가이드 준수 여부 체크`: checkbox, 선택

AI 검수 리스너 실행에는 아래 환경변수가 필요합니다.

- `NOTION_TOKEN`: Notion API 토큰
- `NOTION_DATABASE_ID`: 검수 대상 Notion 데이터베이스 ID
- `GEMINI_API_KEY`: Gemini API 키
- `NOTION_REFERENCE_PAGE_ID`: 기본 세계관 기준 페이지 ID, 선택
- `GEMINI_MODEL`: 사용할 Gemini 모델명, 선택. 기본값은 `gemini-2.5-flash`
- `POLL_INTERVAL_SECONDS`: 반복 실행 시 조회 주기, 선택. 기본값은 `10`
