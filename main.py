from fastapi import FastAPI
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel

app = FastAPI()

vertexai.init(
    project="YOUR_PROJECT_ID",
    location="asia-northeast3"
)

model = GenerativeModel("gemini-1.5-pro")

class Job(BaseModel):
    type: str

@app.post("/")
async def run_job(job: Job):
    job_type = job.type

    if job_type == "today_genie":
        response = model.generate_content("오늘 블로그 글을 작성해줘")
        return {
            "status": "ok",
            "type": "today_genie",
            "content": response.text
        }

    elif job_type == "tomorrow_genie":
        response = model.generate_content("내일 트렌드 예측 블로그 글을 작성해줘")
        return {
            "status": "ok",
            "type": "tomorrow_genie",
            "content": response.text
        }

    return {"status": "ok"}
