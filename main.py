import json
import logging
import requests
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel

from prompts import build_full_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("genie-blog-run")

app = FastAPI(title="genie-blog-run")

# --------------------------------------------------
# PROJECT SETTINGS
# --------------------------------------------------

PROJECT_ID = "gen-lang-client-0667098249"
VERTEX_LOCATION = "global"
VERTEX_MODEL = "gemini-2.5-flash"

SUPPORTED_MODES = ["today_genie", "tomorrow_genie"]

# --------------------------------------------------
# WEATHER API
# --------------------------------------------------

WEATHER_API_KEY = "657ae8a89b6e8db019070e95e4305d75"
WEATHER_CITY = "Seoul"

# --------------------------------------------------
# Vertex AI initialization
# --------------------------------------------------

vertexai.init(
    project=PROJECT_ID,
    location=VERTEX_LOCATION
)

model = GenerativeModel(VERTEX_MODEL)

# --------------------------------------------------
# REQUEST MODEL
# --------------------------------------------------

class Job(BaseModel):
    type: str

# --------------------------------------------------
# WEATHER SERVICE
# --------------------------------------------------

def fetch_weather():

    url = "https://api.openweathermap.org/data/2.5/forecast"

    params = {
        "q": WEATHER_CITY,
        "appid": WEATHER_API_KEY,
        "units": "metric",
        "lang": "kr"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        tomorrow = datetime.utcnow() + timedelta(days=1)
        target = tomorrow.strftime("%Y-%m-%d")

        temps = []
        conditions = []

        for item in data["list"]:
            if item["dt_txt"].startswith(target):

                temps.append(item["main"]["temp"])

                conditions.append(
                    item["weather"][0]["description"]
                )

        if not temps:
            return "weather data unavailable"

        return f"""
weather_summary: {conditions[0]}
temperature_min: {min(temps)}
temperature_max: {max(temps)}
""".strip()

    except Exception:
        logger.exception("Weather fetch failed")
        return "weather data unavailable"

# --------------------------------------------------
# runtime input builder
# --------------------------------------------------

def build_runtime_input(mode: str) -> str:

    if mode == "today_genie":

        return """
target_date: 오늘
target_city: 서울
reference_time: 오전 6시 30분
briefing_type: 한국 주식시장 개장 전 브리핑

market_context:
- overnight_us_market: 데이터 미연동
- kospi_kosdaq_outlook: 데이터 미연동
- usdkrw: 데이터 미연동
- treasury_yield: 데이터 미연동
- oil_price: 데이터 미연동
- bitcoin: 데이터 미연동
- key_macro_events: 데이터 미연동
- sector_watch: 데이터 미연동
- major_news: 데이터 미연동

writing_goal:
- 장 시작 전 핵심 포인트 정리
- 돈이 될 만한 정보 우선
- 과장 없이 설명
- 활기찬 아침 인사 포함
""".strip()

    if mode == "tomorrow_genie":

        weather = fetch_weather()

        return f"""
target_date: 내일
target_city: 서울
forecast_reference_datetime_kst: 내일 06:00
briefing_type: 내일 날씨 및 생활정보 브리핑

weather_context:
{weather}

image_context:
- reference_image_studio_url: 미입력
- reference_image_outdoor_url: 미입력

writing_goal:
- 오늘도 수고한 독자를 다정하게 다독이기
- 내일 날씨 쉽게 설명
- 옷차림과 생활 팁 제공
- 따뜻한 마무리
""".strip()

    raise ValueError(f"Unsupported mode: {mode}")

# --------------------------------------------------
# JSON parsing safety
# --------------------------------------------------

def safe_json_load(content: str):

    try:
        return json.loads(content)

    except Exception:

        cleaned = content.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]

        cleaned = cleaned.replace("json", "").strip()

        return json.loads(cleaned)

# --------------------------------------------------
# JSON validation
# --------------------------------------------------

def validate_ai_output(content: str):

    parsed = safe_json_load(content)

    required_keys = [
        "html_page",
        "email_body_html",
        "naver_blog_body_html"
    ]

    for key in required_keys:
        if key not in parsed:
            raise RuntimeError(f"Missing required key: {key}")

    return parsed

# --------------------------------------------------
# health check
# --------------------------------------------------

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "location": VERTEX_LOCATION,
        "model": VERTEX_MODEL,
        "supported_modes": SUPPORTED_MODES
    }

# --------------------------------------------------
# main endpoint
# --------------------------------------------------

@app.post("/")
async def run_job(job: Job):

    try:

        if job.type not in SUPPORTED_MODES:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 type입니다: {job.type}"
            )

        runtime_input = build_runtime_input(job.type)

        full_prompt = build_full_prompt(
            mode=job.type,
            runtime_input=runtime_input
        )

        logger.info(
            "Generating content | mode=%s | prompt_size=%s",
            job.type,
            len(full_prompt)
        )

        response = model.generate_content(
            full_prompt,
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 8192
            }
        )

        content = getattr(response, "text", None)

        if not content:
            raise RuntimeError("Vertex AI 응답 text가 비어 있습니다.")

        try:

            validated = validate_ai_output(content)

            return {
                "status": "generated",
                "type": job.type,
                "content": validated
            }

        except Exception:

            logger.warning("JSON parsing failed, returning raw output")

            return {
                "status": "generated_raw",
                "type": job.type,
                "raw": content
            }

    except HTTPException:
        raise

    except Exception as e:

        logger.exception("run_job failed")

        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)}"
        )
