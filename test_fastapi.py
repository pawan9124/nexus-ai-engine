from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.testclient import TestClient

app = FastAPI()

class ChatRequest(BaseModel):
    question:str
    session_id: str

@app.post("/api/chat")
async def chat_with_documents(request: ChatRequest):
    return {"status": "ok", "question": request.question, "session_id": request.session_id}

client = TestClient(app)

response = client.post("/api/chat", json={
    "question": "Hello",
    "session_id": "123"
})
print("JSON request:", response.status_code, response.json())

# Now what if we send it without json=, but using data= as string?
response = client.post("/api/chat", data='{"question": "Hello", "session_id": "123"}', headers={"Content-Type": "application/json"})
print("String data with header:", response.status_code, response.json())
