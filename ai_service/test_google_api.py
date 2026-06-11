from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv
import os

load_dotenv()

print("Testing Embeddings Model...")
try:
    embeddings_model = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2-preview")
    res = embeddings_model.embed_query("hi")
    print("Embeddings Model OK, dimension:", len(res))
except Exception as e:
    print("Embeddings Model Error:", e)

print("\nTesting Chat Model...")
try:
    llm = ChatGoogleGenerativeAI(model='gemini-2.5-flash', temperature=0)
    res = llm.invoke("hi")
    print("Chat Model OK, response:", res.content)
except Exception as e:
    print("Chat Model Error:", e)
