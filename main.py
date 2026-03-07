from fastapi import FastAPI, Request
import vertexai
from vertexai.generative_models import GenerativeModel

# FastAPI 앱 생성
app = FastAPI()

# Vertex AI 초기화
vertexai.init(
    project="YOUR_PROJECT_ID",   # 여기에 실제 프로젝트 ID 입력
    location="asia-northeast3"
)

# Gemini 모델 로드
model = GenerativeModel("gemini-1.5-pro")

@app.post("/")
async def run_job(request: Request):

    # JSON 요청 안전 처리
    try:
        data = await request.json()
    except:
        data = {}

    job_type = data.get("type")

    # 오늘의 지니 블로그 생성
    if job_type == "today_genie":

        prompt = """
        오늘 날짜 기준으로 한국 블로그 스타일 글을 작성해줘.

        조건
        - 제목 포함
        - 1500자 이상
        - SEO 고려
        - 친근한 블로그 톤
        """

        response = model.generate_content(prompt)

        return {
            "status": "ok",
            "type": "today_genie",
            "content": response.text
        }

    # 내일의 지니 블로그 생성
    elif job_type == "tomorrow_genie":

        prompt = """
        내일 트렌드를 예측하는 블로그 글을 작성해줘.

        조건
        - 제목 포함
        - 1500자 이상
        - 미래 트렌드 중심
        """

        response = model.generate_content(prompt)

        return {
            "status": "ok",
            "type": "tomorrow_genie",
            "content": response.text
        }

    # 기본 응답
    return {"status": "ok"}
