import json
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel

from prompts import build_full_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("genie-blog-run")

app = FastAPI(title="genie-blog-run")

PROJECT_ID = "gen-lang-client-0667098249"
VERTEX_LOCATION = "global"
VERTEX_MODEL = "gemini-2.5-flash"


class Job(BaseModel):
    type: str


def get_model() -> GenerativeModel:
    vertexai.init(
        project=PROJECT_ID,
        location=VERTEX_LOCATION
    )
    return GenerativeModel(VERTEX_MODEL)


def build_runtime_input(mode: str) -> str:
    if mode == "today_genie":
        return """
target_date: 오늘
target_city: 서울
reference_time: 오전 6시 30분
briefing_type: 한국 주식시장 개장 전 브리핑

market_context:
- overnight_us_market: 미입력
- kospi_kosdaq_outlook: 미입력
- usdkrw: 미입력
- treasury_yield: 미입력
- oil_price: 미입력
- bitcoin: 미입력
- key_macro_events: 미입력
- sector_watch: 미입력
- major_news: 미입력

writing_goal:
- 장 시작 전 핵심 포인트를 빠르게 정리
- 돈이 될 만한 정보 우선 정리
- 과장 없이 명확하게 설명
- 활기찬 아침 인사와 마무리 포함
""".strip()

    if mode == "tomorrow_genie":
        return """
target_date: 내일
target_city: 서울
forecast_reference_datetime_kst: 내일 06:00
briefing_type: 내일 날씨 및 생활정보 브리핑

weather_context:
- weather_summary: 미입력
- sky_condition: 미입력
- precipitation_type: 미입력
- precipitation_probability: 미입력
- temperature_current_0600: 미입력
- temperature_min: 미입력
- temperature_max: 미입력
- feels_like_min: 미입력
- feels_like_max: 미입력
- humidity: 미입력
- wind_speed: 미입력
- air_quality_note: 미입력
- season_context: 미입력

image_context:
- reference_image_studio_url: 미입력
- reference_image_outdoor_url: 미입력

writing_goal:
- 오늘도 수고한 독자를 다정하게 다독이기
- 내일 날씨를 쉽게 설명하기
- 옷차림과 생활 팁 제공
- 따뜻한 마무리 포함
""".strip()

    raise ValueError(f"Unsupported mode: {mode}")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "location": VERTEX_LOCATION,
        "model": VERTEX_MODEL,
        "supported_modes": ["today_genie", "tomorrow_genie"]
    }


@app.post("/")
async def run_job(job: Job):
    try:
        if job.type not in ["today_genie", "tomorrow_genie"]:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 type입니다: {job.type}"
            )

        model = get_model()
        runtime_input = build_runtime_input(job.type)
        full_prompt = build_full_prompt(
            mode=job.type,
            runtime_input=runtime_input
        )

        logger.info("Generating content for mode=%s", job.type)
        response = model.generate_content(full_prompt)
        content = getattr(response, "text", None)

        if not content:
            raise RuntimeError(f"Vertex AI 응답 text가 비어 있습니다. raw={response}")

        return {
            "status": "ok",
            "type": job.type,
            "prompt_used": job.type,
            "content": content
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception("run_job failed")
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)}"
        )
