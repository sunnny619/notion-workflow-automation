import json
import os
import re
import time
from typing import Any

import requests


NOTION_VERSION = "2022-06-28"
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
RICH_TEXT_LIMIT = 2000
DEFAULT_POLL_INTERVAL_SECONDS = 10
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ApiRequestError(RuntimeError):
    def __init__(self, status_code, response_text):
        super().__init__(f"API 요청 실패: HTTP {status_code}\n{response_text}")
        self.status_code = status_code
        self.response_text = response_text


def load_dotenv(path=".env"):
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


def env_required(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"필수 환경변수 `{name}`가 설정되지 않았습니다.")
    return value


load_dotenv()

NOTION_TOKEN = env_required("NOTION_TOKEN")
NOTION_DATABASE_ID = env_required("NOTION_DATABASE_ID")
GEMINI_API_KEY = env_required("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
NOTION_REFERENCE_PAGE_ID = os.getenv("NOTION_REFERENCE_PAGE_ID")
POLL_INTERVAL_SECONDS = int(
    os.getenv("POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL_SECONDS))
)


notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

gemini_headers = {"Content-Type": "application/json"}


def request_json(method, url, headers, **kwargs):
    response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    if not response.ok:
        raise ApiRequestError(response.status_code, response.text)
    return response.json() if response.text else {}


def notion_rich_text(content):
    return [
        {"text": {"content": content[index : index + RICH_TEXT_LIMIT]}}
        for index in range(0, len(content), RICH_TEXT_LIMIT)
    ]


def extract_notion_page_id(value):
    if not value:
        return None

    normalized = value.replace("-", "")
    matches = re.findall(r"[0-9a-fA-F]{32}", normalized)
    if not matches:
        return None

    page_id = matches[-1]
    return (
        f"{page_id[0:8]}-{page_id[8:12]}-{page_id[12:16]}-"
        f"{page_id[16:20]}-{page_id[20:32]}"
    )


def fetch_database():
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
    return request_json("GET", url, notion_headers)


def property_type(database, name):
    return database.get("properties", {}).get(name, {}).get("type")


def find_requested_pages(database):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    status_type = property_type(database, "AI 검수 상태")

    if status_type == "select":
        payload = {
            "filter": {
                "property": "AI 검수 상태",
                "select": {"equals": "검수 요청"},
            }
        }
    elif status_type == "status":
        payload = {
            "filter": {
                "property": "AI 검수 상태",
                "status": {"equals": "검수 요청"},
            }
        }
    else:
        raise RuntimeError(
            "Notion DB에 `AI 검수 상태` select/status 속성이 필요합니다."
        )

    return request_json("POST", url, notion_headers, json=payload).get("results", [])


def rich_text_to_plain_text(rich_text):
    return "".join(text_obj.get("plain_text", "") for text_obj in rich_text)


def get_reference_page_id(page):
    properties = page.get("properties", {})
    reference_property = properties.get("세계관 참고 페이지")

    if reference_property:
        property_type_name = reference_property.get("type")
        if property_type_name == "url":
            return extract_notion_page_id(reference_property.get("url"))
        if property_type_name in ["rich_text", "title"]:
            value = rich_text_to_plain_text(reference_property.get(property_type_name, []))
            return extract_notion_page_id(value)

    return extract_notion_page_id(NOTION_REFERENCE_PAGE_ID)


def fetch_page_content(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    blocks = request_json("GET", url, notion_headers).get("results", [])

    page_text = ""
    for block in blocks:
        block_type = block.get("type")
        if block_type in [
            "paragraph",
            "callout",
            "to_do",
            "to_do_item",
            "bulleted_list_item",
            "numbered_list_item",
            "quote",
            "heading_1",
            "heading_2",
            "heading_3",
        ]:
            rich_text = block.get(block_type, {}).get("rich_text", [])
            for text_obj in rich_text:
                page_text += text_obj.get("plain_text", "") + "\n"

        if block_type == "code":
            rich_text = block.get("code", {}).get("rich_text", [])
            for text_obj in rich_text:
                page_text += text_obj.get("plain_text", "") + "\n"

    return page_text


def page_has_ai_result(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    blocks = request_json("GET", url, notion_headers).get("results", [])

    for block in blocks:
        if block.get("type") != "heading_3":
            continue

        heading_text = rich_text_to_plain_text(
            block.get("heading_3", {}).get("rich_text", [])
        )
        if heading_text.strip() == "AI 검수 결과":
            return True

    return False


def extract_gemini_text(response):
    candidates = response.get("candidates", [])
    if not candidates:
        return ""

    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def run_ai_double_inspector(target_text, reference_text):
    prompt = (
        "너는 버추얼 아티스트 브랜드 운영팀의 세계관 검수 담당자다. "
        "기준 노션 페이지의 글을 사실 기준으로 삼아 검수 대상 글과 비교한다. "
        "기준 글에 없는 내용을 단정하거나 기준 글과 충돌하는 표현을 오류로 판단한다. "
        "반드시 한국어로 짧고 실무적으로 답한다.\n\n"
        "아래 두 글을 비교하고 JSON으로만 답해.\n\n"
        "검수 기준:\n"
        "- lore_pass: 검수 대상이 기준 글의 세계관/설정/서사와 충돌하지 않으면 true\n"
        "- brand_pass: 검수 대상 문체가 공지/운영 문서로 쓰기에 부적절하지 않으면 true\n"
        "- lore_reason: 오류 여부와 충돌 지점을 구체적으로 요약\n"
        "- alternative_text: 오류가 있으면 수정 대안, 없으면 그대로 사용 가능하다는 문장\n\n"
        f"[기준 노션 페이지 글]\n{reference_text}\n\n"
        f"[검수 대상 노션 페이지 글]\n{target_text}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {
                    "lore_pass": {"type": "boolean"},
                    "brand_pass": {"type": "boolean"},
                    "lore_reason": {"type": "string"},
                    "alternative_text": {"type": "string"},
                },
                "required": [
                    "lore_pass",
                    "brand_pass",
                    "lore_reason",
                    "alternative_text",
                ],
            },
        },
    }

    url = (
        f"{GEMINI_API_BASE_URL}/models/{GEMINI_MODEL}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )

    response = None
    for attempt in range(1, 4):
        try:
            response = request_json("POST", url, gemini_headers, json=payload)
            break
        except ApiRequestError as exc:
            if exc.status_code not in RETRYABLE_STATUS_CODES or attempt == 3:
                raise

            wait_seconds = attempt * 10
            print(
                f"Gemini 일시 오류 HTTP {exc.status_code}: "
                f"{wait_seconds}초 후 재시도합니다. ({attempt}/3)"
            )
            time.sleep(wait_seconds)

    if response is None:
        raise RuntimeError("Gemini 응답을 받지 못했습니다.")

    output_text = extract_gemini_text(response)
    if not output_text:
        raise RuntimeError(f"Gemini 응답에서 텍스트를 찾지 못했습니다.\n{response}")

    return json.loads(output_text)


def build_status_properties(database, status_name):
    database_properties = database.get("properties", {})
    properties: dict[str, Any] = {}

    if database_properties.get("AI 검수 상태", {}).get("type") == "select":
        properties["AI 검수 상태"] = {"select": {"name": status_name}}
    elif database_properties.get("AI 검수 상태", {}).get("type") == "status":
        properties["AI 검수 상태"] = {"status": {"name": status_name}}

    return properties


def update_page_properties(page_id, properties):
    if not properties:
        return

    page_url = f"https://api.notion.com/v1/pages/{page_id}"
    request_json("PATCH", page_url, notion_headers, json={"properties": properties})


def mark_page_status(database, page_id, status_name):
    update_page_properties(page_id, build_status_properties(database, status_name))


def build_update_properties(database, ai_result):
    database_properties = database.get("properties", {})
    properties = build_status_properties(database, "검수 완료")

    if database_properties.get("세계관 정합성 체크", {}).get("type") == "checkbox":
        properties["세계관 정합성 체크"] = {"checkbox": ai_result["lore_pass"]}

    brand_property = "브랜드 가이드 준수 여부 체크"
    if database_properties.get(brand_property, {}).get("type") == "checkbox":
        properties[brand_property] = {"checkbox": ai_result["brand_pass"]}

    return properties


def update_notion_with_result(database, page_id, ai_result):
    properties = build_update_properties(database, ai_result)
    update_page_properties(page_id, properties)

    if page_has_ai_result(page_id):
        print(f"기존 AI 검수 결과 블록이 있어 본문 추가를 건너뜁니다: {page_id}")
        return

    children_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    result_text = (
        f"세계관 오류 여부: {'없음' if ai_result['lore_pass'] else '있음'}\n\n"
        f"검수 총평: {ai_result['lore_reason']}\n\n"
        f"추천 대안: {ai_result['alternative_text']}"
    )
    children_payload = {
        "children": [
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"text": {"content": "AI 검수 결과"}}]
                },
            },
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": notion_rich_text(result_text),
                    "icon": {"emoji": "✅" if ai_result["brand_pass"] else "⚠️"},
                },
            },
        ]
    }
    request_json("PATCH", children_url, notion_headers, json=children_payload)


def process_requested_pages():
    database = fetch_database()
    requested_pages = find_requested_pages(database)

    if not requested_pages:
        print("검수 요청 상태인 Notion 페이지가 없습니다.")
        return 0

    processed_count = 0
    for page in requested_pages:
        page_id = page["id"]
        print(f"검수 요청된 페이지 발견: {page_id}")
        mark_page_status(database, page_id, "검수 중")

        try:
            extracted_text = fetch_page_content(page_id)
            if not extracted_text.strip():
                print(f"본문 텍스트가 없어 건너뜁니다: {page_id}")
                mark_page_status(database, page_id, "검수 요청")
                continue

            reference_page_id = get_reference_page_id(page)
            if not reference_page_id:
                raise RuntimeError(
                    "`세계관 참고 페이지` 속성 또는 `.env`의 "
                    "`NOTION_REFERENCE_PAGE_ID`가 필요합니다."
                )

            reference_text = fetch_page_content(reference_page_id)
            if not reference_text.strip():
                raise RuntimeError(
                    f"기준 노션 페이지 본문이 비어 있습니다: {reference_page_id}"
                )

            ai_result = run_ai_double_inspector(extracted_text, reference_text)
            update_notion_with_result(database, page_id, ai_result)
            print("노션 페이지에 AI 검수 결과 반영 완료")
            processed_count += 1
        except Exception:
            mark_page_status(database, page_id, "검수 요청")
            raise

    return processed_count


def main():
    run_once = "--once" in os.sys.argv

    if run_once:
        process_requested_pages()
        return

    print(
        "AI 검수 리스너 시작: "
        f"{POLL_INTERVAL_SECONDS}초마다 `검수 요청` 페이지를 확인합니다."
    )

    while True:
        try:
            process_requested_pages()
        except Exception as exc:
            print(f"리스너 처리 중 오류: {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
