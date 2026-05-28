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
