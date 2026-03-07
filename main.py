import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("genie-blog-run")

app = FastAPI(title="genie-blog-run")

# 실제 값 하드코딩
PROJECT_ID = "gen-lang-client-0667098249"
VERTEX_LOCATION = "global"
VERTEX_MODEL = "gemini-1.5-pro"


class Job(BaseModel):
    type: str


def get_model() -> GenerativeModel:
    if not PROJECT_ID:
        raise RuntimeError("PROJECT_ID가 비어 있습니다.")

    if PROJECT_ID == "YOUR_PROJECT_ID":
        raise RuntimeError("PROJECT_ID가 아직 YOUR_PROJECT_ID placeholder 상태입니다.")

    vertexai.init(
        project=PROJECT_ID,
        location=VERTEX_LOCATION
    )

    return GenerativeModel(VERTEX_MODEL)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "location": VERTEX_LOCATION,
        "model": VERTEX_MODEL,
    }


@app.post("/")
async def run_job(job: Job):
    try:
        model = get_model()

        if job.type == "today_genie":
            prompt = "오늘 블로그 글을 작성해줘"

        elif job.type == "tomorrow_genie":
            prompt = "내일 트렌드 예측 블로그 글을 작성해줘"

        else:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 type입니다: {job.type}"
            )

        response = model.generate_content(prompt)
        content = getattr(response, "text", None)

        if not content:
            raise RuntimeError(f"Vertex AI 응답 text가 비어 있습니다. raw={response}")

        return {
            "status": "ok",
            "type": job.type,
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
