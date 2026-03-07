from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/")
async def run_job(request: Request):

    try:
        data = await request.json()
    except:
        data = {}

    job_type = data.get("type")

    if job_type == "today_genie":
        print("Today Genie Triggered")

    elif job_type == "tomorrow_genie":
        print("Tomorrow Genie Triggered")

    return {"status": "ok"}
