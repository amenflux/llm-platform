# ═══════════════════════════════════════════════════════════════
# IMPORTS — bring in toolboxes full of machines we want to use
# ═══════════════════════════════════════════════════════════════

import logging   # toolbox for writing log messages
import time      # toolbox for anything time-related (clocks, timers)
import uuid      # toolbox for making unique ids

from fastapi import FastAPI, HTTPException                         # from the fastapi toolbox, take 2 specific tools
from pydantic import BaseModel                                     # from the pydantic toolbox, take the BaseModel blueprint
from openai import OpenAI                                          # from the openai toolbox, take the OpenAI machine
from prometheus_fastapi_instrumentator import Instrumentator       # from the prometheus_fastapi_instrumentator toolbox, take the Instrumentator machine
from prometheus_client import Counter                              # from the pprometheus_client toolbox, take the machine toolbox


# ═══════════════════════════════════════════════════════════════
# LOGGING SETUP — runs ONCE, when the app starts
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(          # toolbox=logging, machine=basicConfig, () = RUN it. Sets up how logs behave.
    level=logging.INFO,       # slot "level" ← the constant INFO (a noun; ALL-CAPS = constant). Means: show INFO and anything more serious. Without this line, logging.info() prints NOTHING.
    format="%(asctime)s %(levelname)s %(message)s",  # slot "format" ← TEXT (in quotes). A template for each log line: %(asctime)s = the timestamp, %(levelname)s = INFO/ERROR, %(message)s = whatever you wrote. Result: "2026-07-16 14:02 INFO your message"
)


# ═══════════════════════════════════════════════════════════════
# THE APP + THE LLM CLIENT + THE INSTRUMENTATOR
# ═══════════════════════════════════════════════════════════════

app = FastAPI()   # RUN the FastAPI machine → it hands back an application object → store it in the box named "app"

Instrumentator().instrument(app).expose(app)

llm_tokens_total = Counter(
    "llm_tokens_total",              # the metric name Prometheus will show
    "Total tokens processed",        # a human description
    ["type"],                        # a label so we can split prompt vs completion
)


client = OpenAI(                           # RUN the OpenAI machine → hands back a client object → store it in the box "client"
    base_url="http://localhost:11434/v1",  # slot "base_url" ← TEXT. Points this client at YOUR local Ollama instead of OpenAI's servers.
    api_key="ollama",                      # slot "api_key" ← TEXT. A dummy value — local Ollama ignores it, but the library insists on something.
)


# ═══════════════════════════════════════════════════════════════
# THE REQUEST SHAPE — what a caller must send us
# ═══════════════════════════════════════════════════════════════

class GenerateRequest(BaseModel):  # define a BLUEPRINT named GenerateRequest, built on top of pydantic's BaseModel (which gives us free validation)
    prompt: str                    # field "prompt" must be TEXT. No default value → it is REQUIRED.
    model: str = "llama3.2:3b"     # field "model" must be TEXT, and defaults to "llama3.2:3b" → so it's OPTIONAL


# ═══════════════════════════════════════════════════════════════
# ENDPOINT 1 — the root
# ═══════════════════════════════════════════════════════════════

@app.get("/")        # DECORATOR = a label stuck on the function below. Says: when a GET request arrives at path "/", run this function.
def read_root():     # DEFINE a machine named read_root. Empty () = it takes no inputs.
    return {"message": "Hello World"}  # hand back a DICTIONARY (labeled data): key "message" → value "Hello World". FastAPI converts it to JSON.


# ═══════════════════════════════════════════════════════════════
# ENDPOINT 2 — generate
# ═══════════════════════════════════════════════════════════════

@app.post("/generate")                        # label: when a POST request arrives at "/generate", run the function below.
def generate_text(payload: GenerateRequest):  # DEFINE machine "generate_text". It takes ONE input, named "payload", which must match the GenerateRequest blueprint.

    request_id = str(uuid.uuid4())  # NESTED: inner uuid.uuid4() RUNS first → makes a unique id. Then str() RUNS with that as input → turns it into text. Result goes in box "request_id".
    start = time.perf_counter()     # toolbox=time, machine=perf_counter, RUN it → hands back the clock reading RIGHT NOW → store in box "start"

    try:                            # "TRY the following. If anything blows up, jump to the except block instead of crashing."

        response = client.chat.completions.create(  # walk: client → chat → completions → RUN the create machine (it touches the "("). Whatever comes back goes in the box "response".
            model=payload.model,                    # slot "model" ← NO QUOTES = a lookup: go into the payload box, take its model value
            messages=[{"role": "user", "content": payload.prompt}],  # slot "messages" ← a LIST (numbered, [ ]) holding ONE DICTIONARY (labeled, { }). Inside: "role"→"user" (both literal TEXT), "content"→ payload.prompt (a LOOKUP). It's a LIST because a conversation is a sequence — one message today, ten later.
        )

        answer = response.choices[0].message.content                        # NO PARENTHESES anywhere = pure data fetch. response → choices (a LIST — the API can return several alternative answers) → [0] = take the FIRST one (Python counts from 0) → message → content = the actual text.
        prompt_tokens = response.usage.prompt_tokens                        # fetch: response → usage → prompt_tokens. How many tokens the INPUT cost.
        completion_tokens = response.usage.completion_tokens                # fetch: how many tokens the OUTPUT cost.
        llm_tokens_total.labels(type="prompt").inc(prompt_tokens)           # Picks the prompt slice
        llm_tokens_total.labels(type="completion").inc(completion_tokens)   # Increments it by that many
        total_tokens = response.usage.total_tokens                          # fetch: the two added together.
        latency = time.perf_counter() - start                               # RUN the clock again (time NOW) minus "start" (the time from BEFORE) = seconds elapsed. Store in box "latency".

        logging.info(  # toolbox=logging, machine=info, RUN it → writes ONE log line at INFO level
            f"request_id={request_id} model={payload.model} status=success "      # f"..." = an F-STRING: text where anything in {curly braces} gets swapped for that box's value
            f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} "  # (strings sitting next to each other automatically glue into one)
            f"total_tokens={total_tokens} latency={latency:.3f}s"                    # :.3f = show that number with 3 decimal places (2.431 instead of 2.4310938...)
        )

        return {"response": answer}  # hand back a DICTIONARY: key "response" → the model's text. FastAPI turns it into JSON.

    except Exception as e:  # "if ANYTHING above blew up, catch the error object and put it in a box named e"
        latency = time.perf_counter() - start  # measure how long it ran before it failed
        logging.error(  # machine = error → writes an ERROR-level log line (more serious than INFO, so you can alert on it separately)
            f"request_id={request_id} model={payload.model} status=error "
            f"latency={latency:.3f}s error={e}"  # include the actual error text from box e
        )
        raise HTTPException(status_code=500, detail="LLM request failed")  # RUN the HTTPException machine and "raise" it → FastAPI sends the caller a clean 500 error instead of an ugly crash

