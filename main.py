from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI

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
    response = client.chat.completions.create(
        model=payload.model,
        messages=[{"role": "user", "content": payload.prompt}],
    )
    answer = response.choices[0].message.content
    return {"response": answer}