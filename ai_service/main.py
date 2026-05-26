from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_community.document_loaders import PyPDFLoader 
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_mongodb.vectorstores import MongoDBAtlasVectorSearch
from langchain_mongodb.chat_message_histories import MongoDBChatMessageHistory
from pymongo import MongoClient
from dotenv import load_dotenv
import shutil
import os

# Load the environment variables (Your Google API Key)
load_dotenv()
MONGO_URI= os.getenv("MONGO_URI")

# 2. Initialize MongoDB connection 
# We connect gloabbly so we don't open a anew conection on every API call
client = MongoClient(MONGO_URI)
db = client["enterprise_rag"]
collection = db['document_chunks']

app = FastAPI()

# Initialize the Google Embeddings Model
# We use text-embeddings-004, Google's latest emebedding model
embeddings_model =  GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2-preview")

# The LLM (For acutally talking/answering)
# We use gemini-2.5-flahs because it is lightning fast for RAG
llm = ChatGoogleGenerativeAI(model='gemini-2.5-flash', temperature=0)

# THE 2026 UPGRADE: Using the official LangCHain MongoDB vector Store abstraction 
# This will replace the $vector Search we are introducing before
vector_store = MongoDBAtlasVectorSearch(
    collection=collection,
    embedding=embeddings_model,
    index_name="vector_index"
)

class ChatRequest(BaseModel):
    question:str
    session_id: str # The new ID we will use to look up the database

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), session_id:str = Form(...)):
    # 1. Save teh upload file to the temporarily so Langchain can read it
    file_location = f"temp_{file.filename}"

    try:
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Use Langchain to read the PDF
        loader = PyPDFLoader(file_location)
        raw_documents =  loader.load()

        # 3. CHUKING: Split the text into manageable pieces
        #chunk_overlap ensueres setences at the edge are't cut off awkwardly
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        chunks = text_splitter.split_documents(raw_documents)

        # Attach the session_id in every chunks
        for chunk in chunks:
            chunk.metadata['session_id'] = session_id


        # THE 2026 UPGRADE: Let the vector store handle the database insertion automatically
        vector_store.add_documents(chunks)


        return {
            "status": "success",
            "message": f"Successfully vectorized and saved {len(chunks)} chunks to LangChain VectorStore.",
            "filename": file.filename
        }

    finally:
        # 5. Clean up the temp file even if the codef fails
        if os.path.exists(file_location):
            os.remove(file_location)

@app.post("/api/chat")
async def chat_with_documents(request: ChatRequest):
    try:
        # 1. Connect to our specific user's chat history in MongoDB
        chat_history = MongoDBChatMessageHistory(
            session_id=request.session_id,
            connection_string=MONGO_URI,
            database_name="enterprise_rag",
            collection_name="chat_histories" # A new collection will be auto-created
        )

        # 2. Retrieve past message from the database
        past_messages = chat_history.messages
        formatted_history = "\n".join([f"{msg.type.capitalize()}: {msg.content}" for msg in past_messages])

        # 3. Retrieve context from Vector Store
        # We tell LangChain to search MongoDB and return the top 3 closest matches
        retriever =  vector_store.as_retriever(search_kwargs={"k":3, 'pre_filter':{"session_id": {"$eq": request.session_id}}})

        # Fetch the relevant documents automatically
        relevant_docs = retriever.invoke(request.question)

        if not relevant_docs:
            return {"answer": "I don't have any documents uploaded to answer that."}

        # Combine the retrieved text
        context = "\n\n".join([doc.page_content for doc in relevant_docs])   

        # Ask the LLM to answer
        prompt = f"""
        You are an expert Enterprise system. Answer the user's question using ONLY the context provided below. 
        Take into account the Previous Conversation if it is relevant to the new question.
        
        Previous Conversation:
        {formatted_history}
        
        Context:
        {context}
        
        Current Question: {request.question}
        """
        async def generate_streaming_response():

            full_response = ""

            # Stream the chunks to the frontend instantly

            # .astream() tells langchain to stream the response asynchronously
            async for chunk in llm.astream(prompt):
                full_response += chunk.content
                # We yeild raw text chunks.
                yield chunk.content
            
            # ONCE THE STREAM IS DONE: Save everything to MongoDB!
            chat_history.add_user_message(request.question)
            chat_history.add_ai_message(full_response)

        # Return a StreamingResponse instead of standard JSON dict
        return StreamingResponse(
            generate_streaming_response(),
            media_type="text/event-stream"
        )
    except Exception as e:
        print("Error in chat",e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/api/sessions')
async def get_all_sessions():
    try:
        # LangChain asvaes sthe IDS under the exact field name "SessionId"
        # .distinct() gets a list of unique IDs without downloading the whole database
        session_ids = collection.database['chat_histories'].distinct('SessionId')
        print("Essions::;",session_ids)
        return { "sessions": session_ids}
    except Exception as e: 
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/api/history/{session_id}')
async def get_session_history(session_id:str):
    try:
        # Connect to MongoDB just like we do in the chat route
         chat_history = MongoDBChatMessageHistory(
            session_id=session_id,
            connection_string=MONGO_URI,
            database_name="enterprise_rag",
            collection_name="chat_histories"
         )

         print("chat_history",chat_history)

         # Translate LangChain's internal message objecst back into our simple React form
         formatted_messages = []
         for msg in chat_history.messages:
            formatted_messages.append({
                "type": "user" if msg.type == 'human' else 'ai',
                "text": msg.content
            })

         return { "messages": formatted_messages}

    except Exception as e:
        print("error",e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/health')
async def health_check():
    return {"status": "AI Brain is awake"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    print("Running AI service on the port : 8000")