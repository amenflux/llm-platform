import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

app = FastAPI ()

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

class GenerateRequest(BaseModel):
    prompt: str
    model: str = "llama3.2:3b"


@app.get("/")
def read_root():
    return {"message": "Hello, my first API is alive!"}

@app.post("/generate")
def generate_text(payload: GenerateRequest):
    request_id = str(uuid.uuid4())
    start = time.perf_counter()

    try:
        response = client.chat.completions.create(
            model=payload.model,
            messages=[{"role": "user", "content": payload.prompt}],
        )

        answer = response.choices[0].message.content
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        latency = time.perf_counter() - start

        logging.info(
            f"request_id={request_id} model={payload.model} status=success "
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "
            f"total_tokens={total_tokens} latency={latency:.3f}s"
        )

        return {"response": answer}

    except Exception as e:
        latency = time.perf_counter() - start
        logging.error(
            f"request_id={request_id} model={payload.model} status=error "
            f"latency={latency:.3f}s error={e}"
        )
        raise HTTPException(status_code=500, detail="LLM request failed")