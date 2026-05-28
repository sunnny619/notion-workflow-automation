import argparse
import ast
import os
import random
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pymysql
import requests


DEFAULT_WINNER_COUNT = 1
NOTION_API_URL = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"
NOTION_RICH_TEXT_LIMIT = 2000
SEED_DEMO_SQL = "seed_demo.sql"


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    notion_token: str
    notion_database_id: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_db: str
    winner_count: int
    ip_limit: int
    branding_team_page_id: str | None


def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"필수 환경변수 `{name}`가 설정되지 않았습니다.")
    return value


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        notion_token=env_required("NOTION_TOKEN"),
        notion_database_id=env_required("NOTION_DATABASE_ID"),
        mysql_host=os.getenv("MYSQL_HOST", "localhost"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=env_required("MYSQL_PASSWORD"),
        mysql_db=os.getenv("MYSQL_DB", "vlast_promotion"),
        winner_count=int(os.getenv("WINNER_COUNT", str(DEFAULT_WINNER_COUNT))),
        ip_limit=int(os.getenv("IP_LIMIT", "2")),
        branding_team_page_id=os.getenv("NOTION_BRANDING_TEAM_PAGE_ID"),
    )


def mysql_config(settings: Settings) -> dict[str, Any]:
    return {
        "host": settings.mysql_host,
        "port": settings.mysql_port,
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "db": settings.mysql_db,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def fetch_participants(settings: Settings) -> list[dict[str, Any]]:
    connection = pymysql.connect(**mysql_config(settings))
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_id, nickname, content, user_ip
                FROM promotion_participants
                WHERE user_id IS NOT NULL
                  AND nickname IS NOT NULL
                  AND content IS NOT NULL
                  AND user_ip IS NOT NULL
                """
            )
            return list(cursor.fetchall())
    finally:
        connection.close()


def fetch_mock_participants(seed_path: str = SEED_DEMO_SQL) -> list[dict[str, Any]]:
    with open(seed_path, encoding="utf-8") as seed_file:
        seed_sql = seed_file.read()

    match = re.search(
        r"INSERT\s+INTO\s+promotion_participants\s*"
        r"\(\s*user_id\s*,\s*nickname\s*,\s*content\s*,\s*user_ip\s*\)"
        r"\s*VALUES\s*(.*?);",
        seed_sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError(f"`{seed_path}`에서 샘플 참여자 INSERT 구문을 찾지 못했습니다.")

    rows = ast.literal_eval(f"[{match.group(1)}]")
    return [
        {
            "user_id": user_id,
            "nickname": nickname,
            "content": content,
            "user_ip": user_ip,
        }
        for user_id, nickname, content, user_ip in rows
    ]


def pick_winners(
    participants: list[dict[str, Any]],
    winner_count: int,
    ip_limit: int,
    rng: random.Random | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    rng = rng or random.SystemRandom()

    ip_counts: dict[str, int] = {}
    for participant in participants:
        ip = str(participant["user_ip"])
        ip_counts[ip] = ip_counts.get(ip, 0) + 1

    abuser_ips = {ip for ip, count in ip_counts.items() if count > ip_limit}
    seen_user_ids: set[str] = set()
    valid_pool: list[dict[str, Any]] = []

    for participant in participants:
        user_id = str(participant["user_id"])
        if str(participant["user_ip"]) in abuser_ips:
            continue
        if user_id in seen_user_ids:
            continue

        seen_user_ids.add(user_id)
        valid_pool.append(participant)

    winners = rng.sample(valid_pool, min(len(valid_pool), winner_count))
    return winners, len(participants), len(valid_pool)


def mask_user_id(user_id: Any) -> str:
    value = str(user_id)
    if len(value) <= 3:
        return "***"
    return f"{value[:-3]}***"


def summarize_content(content: Any, limit: int = 25) -> str:
    value = str(content).replace("\n", " ").strip()
    return f"{value[:limit]}..." if len(value) > limit else value


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def notion_rich_text(content: str) -> list[dict[str, dict[str, str]]]:
    return [
        {"text": {"content": content[index : index + NOTION_RICH_TEXT_LIMIT]}}
        for index in range(0, len(content), NOTION_RICH_TEXT_LIMIT)
    ]


def extract_notion_page_id(value: str | None) -> str | None:
    if not value:
        return None

    normalized = value.replace("-", "")
    match = re.search(r"[0-9a-fA-F]{32}", normalized)
    if not match:
        return None

    page_id = match.group(0)
    return (
        f"{page_id[0:8]}-{page_id[8:12]}-{page_id[12:16]}-"
        f"{page_id[16:20]}-{page_id[20:32]}"
    )


def generate_markdown(
    winners: list[dict[str, Any]], total_raw: int, total_valid: int
) -> str:
    current_date = datetime.now().strftime("%Y년 %m월 %d일")

    lines = [
        "### 버추얼 아티스트 컴백 프로모션 미션 이벤트 당첨자 발표",
        "",
        "안녕하세요, 브랜딩팀입니다.",
        "엄격한 세계관 정합성 검토 및 어뷰징 필터링을 거쳐 최종 당첨자를 발표합니다.",
        "",
        "---",
        "",
        f"#### 최종 당첨자 명단 (총 참여: {total_raw}명 / 유효 참여: {total_valid}명)",
        "| 순번 | 유저 ID | 닉네임 | 선정된 팬 피드백 (요약) |",
    ]

    for index, winner in enumerate(winners, 1):
        lines.append(
            "| {index} | {user_id} | {nickname} | \"{content}\" |".format(
                index=index,
                user_id=mask_user_id(winner["user_id"]),
                nickname=markdown_cell(winner["nickname"]),
                content=markdown_cell(summarize_content(winner["content"])),
            )
        )

    lines.extend(
        [
            "",
            "---",
            f"공고일자: {current_date}",
            "본 추첨은 시스템 코드를 통해 공정하게 진행되었습니다.",
        ]
    )
    return "\n".join(lines)


def notion_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def fetch_notion_database(settings: Settings) -> dict[str, Any]:
    response = requests.get(
        f"https://api.notion.com/v1/databases/{settings.notion_database_id}",
        headers=notion_headers(settings),
        timeout=20,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Notion 데이터베이스 조회 실패: HTTP {response.status_code}\n{response.text}"
        )

    return response.json()


def add_current_date_property(
    properties: dict[str, Any], database_properties: dict[str, Any]
) -> None:
    preferred_names = ["날짜", "일자", "공고일자", "Date"]
    date_property_name = next(
        (
            name
            for name in preferred_names
            if database_properties.get(name, {}).get("type") == "date"
        ),
        None,
    )

    if not date_property_name:
        date_property_name = next(
            (
                name
                for name, definition in database_properties.items()
                if definition.get("type") == "date"
            ),
            None,
        )

    if date_property_name:
        properties[date_property_name] = {"date": {"start": date.today().isoformat()}}


def add_branding_team_relation(
    properties: dict[str, Any], database_properties: dict[str, Any], settings: Settings
) -> None:
    team_page_id = extract_notion_page_id(settings.branding_team_page_id)
    if not team_page_id:
        return

    teams_property_name = next(
        (
            name
            for name in ["Teams", "Team", "팀"]
            if database_properties.get(name, {}).get("type") == "relation"
        ),
        None,
    )

    if teams_property_name:
        properties[teams_property_name] = {"relation": [{"id": team_page_id}]}


def build_notion_properties(database: dict[str, Any], settings: Settings) -> dict[str, Any]:
    database_properties = database.get("properties", {})
    title_property_name = next(
        (
            name
            for name, definition in database_properties.items()
            if definition.get("type") == "title"
        ),
        None,
    )

    if not title_property_name:
        raise RuntimeError("Notion 데이터베이스에서 title 타입 속성을 찾지 못했습니다.")

    properties = {
        title_property_name: {
            "title": [
                {"text": {"content": "[운영] 팬 이벤트 최종 당첨자 공고 배포 요망"}}
            ]
        }
    }

    if database_properties.get("업무단계", {}).get("type") == "select":
        properties["업무단계"] = {"select": {"name": "4단계 운영"}}

    add_current_date_property(properties, database_properties)
    add_branding_team_relation(properties, database_properties, settings)

    return properties


def notion_payload(
    settings: Settings, markdown_content: str, database: dict[str, Any]
) -> dict[str, Any]:
    return {
        "parent": {"database_id": settings.notion_database_id},
        "properties": build_notion_properties(database, settings),
        "children": [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [
                        {"text": {"content": "즉시 복사용 마크다운 템플릿"}}
                    ]
                },
            },
            {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": notion_rich_text(markdown_content),
                    "language": "markdown",
                },
            },
        ],
    }


def send_to_notion(settings: Settings, markdown_content: str) -> str:
    database = fetch_notion_database(settings)

    response = requests.post(
        NOTION_API_URL,
        headers=notion_headers(settings),
        json=notion_payload(settings, markdown_content, database),
        timeout=20,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Notion API 전송 실패: HTTP {response.status_code}\n{response.text}"
        )

    page_id = response.json().get("id", "unknown")
    return page_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MySQL 참여 데이터를 정제해 당첨자를 추첨하고 Notion 운영 티켓을 생성합니다."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Notion에 전송하지 않고 생성된 마크다운만 출력합니다.",
    )
    parser.add_argument(
        "--mock-data",
        action="store_true",
        help="MySQL 대신 코드에 포함된 샘플 참여 데이터를 사용합니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = None if args.mock_data and args.dry_run else load_settings()

    print("[배치 작업 시작] MySQL 데이터 검증 및 추첨 가동...")
    participants = fetch_mock_participants() if args.mock_data else fetch_participants(settings)
    winners, raw_count, valid_count = pick_winners(
        participants,
        winner_count=settings.winner_count if settings else DEFAULT_WINNER_COUNT,
        ip_limit=settings.ip_limit if settings else 2,
    )
    announcement = generate_markdown(winners, raw_count, valid_count)

    if args.dry_run:
        print("\n[DRY RUN] 생성된 공고문\n")
        print(announcement)
        return

    print("정제 완료 데이터를 공식 노션 마스터 위키로 전송 중...")
    if settings is None:
        settings = load_settings()
    page_id = send_to_notion(settings, announcement)
    print(f"성공: 노션 HQ에 당첨자 운영 티켓이 발급되었습니다. page_id={page_id}")


if __name__ == "__main__":
    main()
