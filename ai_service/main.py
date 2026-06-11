from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_community.document_loaders import PyPDFLoader 
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_mongodb.vectorstores import MongoDBAtlasVectorSearch
from langchain_mongodb.chat_message_histories import MongoDBChatMessageHistory
from langchain_core.documents import Document
from langgraph.graph import END, StateGraph
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from pymongo import MongoClient
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict,Any, List, TypedDict
import shutil
import os
import re
import hashlib

# ========================================================
#                   Config Settings
# ========================================================

# Simulate a Redis Cache instance in memory
# In proudction, this would be: redis_client = redis.Redis(host="localhost", port=6379, db=0)
local_redis_cache = {}


# Load the environment variables (Your Google API Key)
load_dotenv()
MONGO_URI= os.getenv("MONGO_URI")

# 2. Initialize MongoDB connection 
# We connect gloabbly so we don't open a anew conection on every API call
client = MongoClient(MONGO_URI)
db = client["enterprise_rag"]
collection = db['document_chunks']
cache_collection = db['semantic_cache']
security_collection = db['security_guardrails']



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Initialize the Google Embeddings Model
# We use text-embeddings-004, Google's latest emebedding model
embeddings_model =  GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2-preview")

# The LLM (For acutally talking/answering)
# We use gemini-2.5-flahs because it is lightning fast for RAG
llm = ChatGoogleGenerativeAI(model='gemma-4-31b-it', temperature=0)

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

# ---------------------------- INTRODUCTION OF LANGGRAPH FOR AGENTIC WORKFLOW--------------------
# LangGraph allows us to build cycles (loops). We are going to give your AI a "State" (memory) and build an architecture known as Self-Reflective RAG (CRAG).
class GraphState(TypedDict):
    question: str # The current user question
    generation: str # The Final AI answer
    documents: List[Document] # The context pulled from MongodDB
    loop_count: int # To prevent infinite loops (cut off after 3 tries)
    allowed_tiers: List[str]
    session_id:str # NEW: The Role based security badge,

# Define the strict JSON schema we ewanat the LLM to putput
class GradeDocuments(BaseModel):
    """
    Binary score for relevance checks on retrieved documents.
    """
    binary_score: str = Field(description="Documents are relevant to the question, 'yes' or 'no'")



#-----------------------------------
    # Reranking setting for the  Hybrid Search combines both algorithms 
    # simultaneously, and merges their results using an algorithm called 
    # Reciprocal Rank Fusion (RRF). ------------------

# 1. Fetch all documetns from MongodDB to  build teh Keyword Index
# (We do this once when the server starts)

print(" BUilding BM25 Keyword Index in memory....")
all_docs_cursor =  vector_store.collection.find({},{"text":1, "session_id":1, "metadata":1})
all_documents = []

for doc in all_docs_cursor:
    if 'text' in doc:
        #Reconstruct the metadata dictionary safely
        doc_metadata = doc.get('metadata',{})

        #Attach the session_id directly into the metadata so BM25 can read it later
        doc_metadata["session_id"] = doc.get('session_id')

        # Create the LangChain DOcument object
        all_documents.append(Document(
            page_content=doc['text'],
            metadata=doc_metadata
        ))
print("All documents length:", len(all_documents))
print("all_documents:",all_documents)

# FIX: Protect against an empty database crash!
if len(all_documents) == 0:
    print(" WARNING: Database is empty! Initializing BM25 with placeholder")
    # We feed a single fake document just so the math engine doesn't crash
    dummy_doc = Document(
        page_content="system initialization placeholder empty document",
        metadata={"security_tier": "PUBLIC", "session_id": "dummy"}
    )
    keyword_retriever = BM25Retriever.from_documents([dummy_doc])
else:
    keyword_retriever = BM25Retriever.from_documents(all_documents)

keyword_retriever.k = 3 # Return the top  3 keyword matches

# Setup your existing Vector Retriever
vector_retriever = vector_store.as_retriever(search_kwargs={"k":3})

# THE MAGIC: Combine them into  a Hybrid Retriever using RRF
hybrid_retriever = EnsembleRetriever(
    retrievers=[keyword_retriever, vector_retriever],
    weights=[0.5,0.5] # 50% keyword, 50% vector
)

print(" Hybrid Search Engine Ready! using RRF")




# ========================================================
#                   Supportive functions
# ========================================================

def static_firewall_router(user_query: str) -> str:
    """
    Step 1: Deterministic Firewall.
    Returns the intent string instantly without hitting an LLM API
    """

    cleaned_query = user_query.strip().lower()

    #1. Caught Greetings / General Pleasantries
    greetings = ['hi', "hello", "hey", "sup", "good morning", "good afternoon", "hola"]
    if cleaned_query in greetings:
        return "GENERIC_GREETING"
    
    # 2. Catch simple Math expression (e.g 45+5, "100*20")

    math_pattern = r'^\d+\s*[\+\-\*\/]\s*\d+$'
    if re.match(math_pattern, cleaned_query):
        return "SIMPLE_MATH"

    # IF it passes both, it requires deeper semantic understanding
    return "UNKNOWN"

# --- STEP 2: AGENTIC LLM ROUTER (FALLBACK) ----
async def determine_intent_with_llm(question: str, formatted_history: str, llm_instance) -> str:
    """ Uses a lightweight structural prompt to classify intent instantly."""
    router_prompt = f"""
    You are an elite intent classification router. Analyze the user's current question and past history.
    Classify the question into EXACTLY one of these categories:
    - VECTOR_RAG: If the user is asking about specific corporate data, documents, files, data lookups, summaries of records, or information that requires external knowledge.
    - GENERIC_CHAT: If it is a general question, coding assistance, hypothetical scenario, or conversational filler that doesn't need document context.
    - MATH: If it requires complex calculation or data logic.

    Previous Conversation:
    {formatted_history}

    Current Question: {question}

    Respond with ONLY the category string (e.g. 'VECTOR_RAG'). Do not include explaination or markdown.
    """

    # Use standard invocation for a fast, single-word token return
    response = await llm_instance.ainvoke(router_prompt)
    raw_content = response.content

    # DEFENSIVE PARSING: Handle Gemma's list format safely
    if isinstance(raw_content, list):
        #Extract the text string out of the first dictionary in the list
        intent_text = raw_content[0].get('text','')
        intent = intent_text.strip().upper()
    else:
        #If it's standard Gemini string, just strip it normally
        intent = raw_content.strip().upper()

    if intent in ["VECTOR_RAG", "GENERIC_CHAT", "MATH"]:
        return intent
    return "VECTOR_RAG" # Default safe fallback




def get_cache_key(intent:str, question:str) -> str:
    """ Creates a unique has for the intent and question to use as a cache key."""
    normalize_str = f"{intent}:{question.strip().lower()}"
    return hashlib.md5(normalize_str.encode()).hexdigest()

# We are introducing the semantich caching in case the if we able to cache the questions and like to see if need similar respose
# ---  NEW: SEMANTIC CACHE HELPER FUNCTIONS ---

async def check_semantic_cache(question: str, threshold: float =0.95) -> str | None:
    """ Embeds the query and checks MongoDB for a mathematical intent match."""

    query_vector = embeddings_model.embed_query(question)

    # 2. Run a mongodb vector search against past cached questions
    pipeline = [
        {
            "$vectorSearch":{
                "queryVector": query_vector,
                "path":"embedding",
                "numCandidates":50,
                "limit":1,
                'index':'semantic_cache_index' # Your Atlas Search Index name
            }
        },
        # Project the score to mathematically verify how close the match is
        {
            "$project":{
                'cached_answer':1,
                'score':{"$meta": "vectorSearchScore"}
            }
        }
    ]

    # Execute the search 
    results = list(cache_collection.aggregate(pipeline))

    # 3. check if the closest match beats our strict 95% threshold
    if results and results[0]['score'] >= threshold:
        print(f" SEMANTIC CACHE HIT! Score: {results[0]['score']}")
        return results[0]['cached_answer']
    
    return None # Cache Miss


# Cache the question and response in the SemanticMongoDB
def save_to_semantic_cache(question:str, answer:str):
    """ Embeds the new question and save it alongside the AI's answer."""
    question_vector = embeddings_model.embed_query(question)
    cache_collection.insert_one({
        "original_question":question,
        "embedding":question_vector,
        "cached_answer":answer
    })

    print(f" Saved new semantic intent to MongoDB Cache")

# Securing the prompt injection guradrails and following the instructions
async def check_security_threat(question: str, threshold: float=0.85)->bool:
    """
    Scans the incoming prompt against known Prompt Injections.
    Returns True if an attack is detected, False if safe
    """
    # 1. Embed the incoming prompt
    query_vector = embeddings_model.embed_query(question)
    
    # 2. Run a MongoDB Vector Search against known attacks
    pipeline = [
        {
            "$vectorSearch":{
                "queryVector": query_vector,
                "path": "embedding",
                "numCandidates": 20,
                "limit":1,
                "index": "security_index"
            }
        },{
            "$project":{
                "attack_type":1,
                "score":{"$meta":"vectorSearchScore"}
            }
        }
    ]

    # Execute the search
    results = list(security_collection.aggregate(pipeline))

    # 3. If the math says this is 85% similar to a know hack, block it!

    if results and results[0]['score'] >= threshold:
        print(f" SECURITY ALERT: Blocked prompt injection ! Score:{results[0]['score']}")
        return True
    return False


# ---------------- LANGGRAPH STATE DEFINITION ----------------

# ---------- WORKER A: THE RETRIEVE NODE -------------
async def retriever_node(state: GraphState)-> GraphState:
    """
    Worker A: Reads the question, runs HYBRID SEARCH (Vector + keywords) and returns the 
    highest ranked documents.

    OUTDATE NOW:Woker A: Reads the question from the state, queries MongoDB, a
    and returns the documents to be added to the state.

    """

    print(" [NODE: RETRIEVE]: Fetching context from from MongoDB...")

    question = state['question']
    loop_count = state.get("loop_count",0)

    # NOw integerate the allowed tiers for the Role based Access to the vectors

    allowed_tiers = state.get('allowed_tiers',['PUBLIC'])
    session_id = state.get("session_id") # Grab the session lock

    # The math Shield for Vector Search
    combined_rabc_session_filter = {
        "$and":[
            {"metadata.security_tier": {"$in": allowed_tiers}},
            {"session_id":{"$eq": session_id}}
        ]
    }
    secure_vector = vector_store.as_retriever(
        search_kwargs={"k": 10, "pre_filter": combined_rabc_session_filter}
    )

    secure_hybrid = EnsembleRetriever(
        retrievers = [keyword_retriever, secure_vector],
        weights=[0.5, 0.5]
    )


    # Initialize the retreiver from your existing vector_store
    # We fetch the top 4 mathematically closest documents
    # retriever = vector_store.as_retreiver(search_kwargs={'k':4})
    
    # Execute the vector search asynchronously
    # documents = await retriever.ainvoke(question)

    # We now use the hybrid_retriever instead of the vector_retriever
    raw_documents = await secure_hybrid.ainvoke(question)

    # The python Shield for Keyword search
    # We must manually drop an unauthorized docs the BM25 keyword engine found
    secure_documents = []
    for doc in raw_documents:
        # Default to PUBLIC if the metadata is missing
        doc_tier = doc.metadata.get('security_tier', "PUBLIC")
        if doc_tier in allowed_tiers:
            secure_documents.append(doc)
    
    print(f" [NODE: RETRIEVE]: Found {len(secure_documents)} authorized chunks.")

    # Return the updated pieces of the state
    # LangGraph automatically merges this dictionary into master GraphState
    return {
        "documents":secure_documents,
        "loop_count":loop_count+1 # Increment the loop counter to prevent infinite loop 
    }


#  -------------- WORKER B: The Grader Node ----------------
async def grade_node(state: GraphState) -> GraphState:
    """
    Worker B: Evaluates retrieved documents.
    Keeps the good ones, throws away the garbage one
    """

    print(" [NODE GRADER]: Evaluating documents relevance....")

    question = state['question']
    documents = state['documents']

    # If retrieval failed entirely, fast -failed to rewrite

    if not documents:
        return { "documents":[]}

    # Bind the strict Pydantic schema to your LLM
    structured_llm_grader = llm.with_structured_output(GradeDocuments)

    # NEW Instruction: Grade the batch as a whole 
    # Since we are now using vector search our retrieval is mathematically precise.
    # We no longer need to filter individual documents.
    # We just need to ask the LLM if the retrieved context is sufficient.
    system_prompt = """
        You are an elite grading system.
        You will be given a batch of  retrieved document chunks.
        If ANY of the chunks contain keywords, facts, or semantic meaning that helps answer the user's question, grade the batch 'yes'. 
        If the entire batch is completely unrelated garbage, grade it 'no'.
        You must output ONLY 'yes' or 'no'.
     """

    grade_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Retreived documents: \n\n {context} \n\n User question: {question}")
    ])

    retrieval_grader = grade_prompt | structured_llm_grader

    # The magic to combine all chunks into one string (Costs $0, takes 0ms)
    combined_context = "\n\n---\n\n".join([doc.page_content for doc in documents])

    # Ask the LLM to grade the entire batch in exactly ONE API call
    result  =  await retrieval_grader.ainvoke({
        "question": question,
        "context": combined_context
    })

    # Log the results for your terminal observability
    if result.binary_score == "yes":
        print(f" [NODE: GRADER] : Batch Approved! Passing {len(documents)} chunks forward.")
        return { "documents": documents}
    else:
        print(f" [NODE: GRADER]  Batch Rejected. Triggering rewrite loop.")
        return {"documents":[]}
    


# --------------- WORKER C: The Rewriter Node --------------
async def rewrite_node(state: GraphState) -> GraphState:
    """
    Worker C: Takes a bad user quesion and rewrites it to be
    mathematically optimal for a Vector Database search.
    """

    print(" [NODE:REWRITER]:  Documents were irrelevant. Rewriting query...")

    question = state['question']

    # The System prompt optimized for vector math keywords
    system_prompt = """ You are an expert search query optimizer.
    Your task is to take a user's poorly worded question and rewrite it to be mathematically optimal for a vector Database cosine similarity search.
    Focus on extracting the core semantic intent, specific nouns, and the most important keywords.
    Do NOT answer the question. Just output the improved search query as a plain string
    """

    rewrite_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ('human', "Original question:{question}")
    ])

    # LCEL Pipe: Prompt -> LLM -> Raw String output
    rewriter_chain = rewrite_prompt | llm | StrOutputParser()

    # Execute the rewrite
    better_question =  await rewriter_chain.ainvoke({"question": question})

    print(f" [NODE: REWRITER]: Old query : '{question}'")
    print(f" [NODE: REWRITER]: New Query: '{better_question}'")

    # We return the new question: LangGraph will override the old question on the clipboard!
    return {"question": better_question}

# ----------- WORKER D: The Generator node ---------------
async def generate_node(state: GraphState) -> GraphState:
    """
    Worker D: Takes the validated documents and the final question, 
    and generates the answer for the user.
    """

    print(" [NODE:GENERATOR] Constructing final answer...")

    question = state['question']
    documents = state['documents']

    # Combine all the approved documents chunks into one big string
    context_text = "\n\n".join([doc.page_content for doc in documents])

    system_prompt = """ You are Enterprise AI Assistant.
    Use the following validated context to answer the user's question.
    If the answer is not fully contained in the context, state that you don don't  have enough information.

    Context:
     {context}
    """

    generate_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])

    # pipe: Prompt -> LLM -> String
    rag_chain = generate_prompt | llm | StrOutputParser()

    # Generate the final response
    final_answer = await rag_chain.ainvoke({"context": context_text, "question": question})

    print(f" [NODE: GENERATOR] Answer generate successfully.")

    # Save the final answer to the state
    return {"generation": final_answer}

# --------------- DECIDE TO GENERATE -------------------
def decide_to_generate(state: GraphState)-> str:
    """
    The Traffic cop: Decide where to send the clipboard next.
    """

    filtered_docs = state.get("documents",[])
    loop_count = state.get("loop_count",0)

    # 1. The Circuit Breaker
    # If the API gets confused and loop 3 times, we force it to stop
    # and just answer with whatever it has
    if loop_count >= 3:
        print(f" [GRAPH] Max loops reached: Forcing generation.")
        return 'generate'
    
    # 2. The Agentic loop
    # If the Grader threw away all documents (filtered_docs is empty)
    # we tell LangGraph to route to the Retriever Node.

    if len(filtered_docs) == 0:
        print(f" [GRAPH] Decision: Documents are bad. Routing to Rewriter")
        return 'rewrite'

    # 3. The Happy path
    # If we have good documents left, route to the final Generator Node!
    print(f" [GRAPH] Decision: Documents are good. Routing to Generator.")
    return 'generate'


# ========================================================
#                   BUILD THE LANGGRAPH WORKFLOW
# ========================================================
# 1. Initialize the Graph with out State
workflow = StateGraph(GraphState)

# 2. Define the "Nodes" (The Physical funtions the AI can execute)
workflow.add_node("retrieve", retriever_node) # fetches from MongoDB
workflow.add_node('grade_documents', grade_node) # checks if docs are relevant 
workflow.add_node("generate", generate_node) #Streams the final answer
workflow.add_node("rewrite_query", rewrite_node) # Improves the seach query

# 3. Define the "Edges" (How the AI moves from node to node)
workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "grade_documents")

# 4. The conditional Edge (The "Thinking" Phase)
# If documents are good -> go to Generate. If bad -> go to Rewrite.

workflow.add_conditional_edges(
    "grade_documents",
    decide_to_generate,
    {
        "generate": "generate",
        "rewrite": "rewrite_query"
    }
)

# If it rewrites, it MUST loop back to retreive new documents
workflow.add_edge("rewrite_query", "retrieve")
workflow.add_edge("generate", END)

# Compile the Graph!
app_brain  = workflow.compile()


# Mock Authentication Dependendcy
def get_current_user():
    """
    Simulate a  decoded JWT token.
    Change 'role' to "EXECUTIVE" or "MANAGER" to test different access levels
    """
    return {
        "username": "pawan",
        "role": "INTERN"
    }
# ========================================================
#                   API's Endpoints
# ========================================================
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
        # Attach the session_id AND the security badge to every chunk
        for chunk in chunks:
            chunk.metadata['session_id'] = session_id
            chunk.metadata['security_tier'] = "PUBLIC" # 🛡️ The RBAC Default!


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
async def chat_with_documents(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        #====================================================
        #   TOLLBOOTH 1: THE SECURITY SHEILD (Vector Math)
        #====================================================
        
        is_attack = await check_security_threat(request.question, threshold=0.85)

        if is_attack:
            # We will kill the request instantnly. Do not pass go. Do not call the LLM.
            raise HTTPException(
                status_code=403,
                detail="Security violation detected. This incident has been logged."
            )
        #===========================================================

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

        # RUN THE DETERMINISTIC ROUTER (0.01ms const)
        intent = static_firewall_router(request.question)

        # RUN THE AGENTIC ROUTER IF UNKNOWN (Fast LLM Check)
        if intent == "UNKNOWN":
            intent = await determine_intent_with_llm(request.question, formatted_history, llm)
        
        print(f"DEBUG LOG: Routed user query with intent -> [{intent}]")

        # =========================================================
        #       NEW: THE CACHING ENGINE LAYER WITH SEMANTIC CACHE
        # =========================================================

        # We only cache MATH and GENERIC queries. We DO NOT cachec VECTOR RAG
        # because the user might have uploaded a new PDF, changing the correct answer! to save the query call to the LLM.
        cache_key = get_cache_key(intent, request.question)

        if intent in ["MATH", "GENERIC_CHAT"]:

            # Tier 1: Exact String Cache (Local Memory / Redis) -> [Cost: $0 | Latency: <1ms ]
            if cache_key in local_redis_cache:
                print(f" CACHE HIT ! Returning instant response for: {request. question}")
                cached_answer = local_redis_cache[cache_key]

                # Yield the cached response as a fast stream so the UI doesnt' break
                async def stream_cache():
                    yield cached_answer
                
                return StreamingResponse(stream_cache(), media_type='text/event-stream')

            
            # Tier 2: Semantic Vector Cche (MongoDB Atlas) -> [Cost: Micro-cents | Latnecy: ~50ms]
            # If exact match fails, we check if they meant the same thing mathematically
            cached_answer = await check_semantic_cache(request.question, threshold=0.95)
            if cached_answer:
                print(f" TIER 2 HIT: Semantic match found in MongoDB Vector search!")

                # Dynamic Optimization: Save this to Tier 1 so the NEXT identical query drops to <1ms

                local_redis_cache[cache_key] = cached_answer

                async def stream_semantic_cache():
                    yield cached_answer
                return StreamingResponse(stream_semantic_cache(), media_type="text/event-stream")
                
        # ====================================



        # ==========================================================
        #    NEW: THE RBAC (Role base Access Control) SECURITY MAP
        # ===========================================================
        user_role = current_user['role']

        # Define who can see what
        role_permissions = {
            "INTERN":['PUBLIC'],
            "MANAGER":['PUBLIC', 'DEPARTMENTAL'],
            "EXECUTIVE":['PUBLIC', "DEPARTMENTAL", "EXECUTIVE"]
        }

        # If the role is weird, default to PUBLIC only (Fail-safe)
        allowed_tiers = role_permissions.get(user_role, ['PUBLIC'])

        print(f" USER ROLE: {user_role} | Granted Access to the: { allowed_tiers}")

        # 4. CHOOSE BRAIN PIPELINE BASED ON INTENT
        context = ""
        system_instructions = " You are an expert enterprise AI system."

        if intent == "VECTOR_RAG":

            # ==================================================
            #  THE NEW AGENTIC BRAIN (RAG) vs STANDARD LLM
            # ==================================================
            print(f" Routing question to LangGraph Agentic Brain...")
        
            final_state = await app_brain.ainvoke({
                "question": request.question,
                "loop_count":0,
                "allowed_tiers": allowed_tiers,
                "session_id":request.session_id # Injected here!,

            })

            final_answer = final_state.get("generation", "I'm sorry, I couldn't find an answer.")

            async def stream_graph_response():
                # Yield the final answer for the frontend
                yield final_answer
                # Save to history
                chat_history.add_user_message(request.question)
                chat_history.add_ai_message(final_answer)

            return StreamingResponse(stream_graph_response(), media_type="text/event-stream")
            # ============= OLD WAY TO HANDLE THE  RAG ==========
            # # Only hit the vector database if explicitly routed here!
            # retriever = vector_store.as_retriever(
            #     search_kwargs = {"k":3, 'pre_filter':{"session_id": {"$eq":request.session_id}}}
            # )


            # # Fetch the relevant documents automatically
            # relevant_docs = retriever.invoke(request.question)

            # if not relevant_docs:
            #     return {"answer": "I don't have any documents uploaded to answer that."}

            # # Combine the retrieved text
            # context = "\n\n".join([doc.page_content for doc in relevant_docs])
            # system_instructions += " Answer the user's question using ONLY the document context provided below." 
        elif intent == "MATH":
            system_instructions += " You are an advanced calculator engine. Focus on absolute mathematical accuracy."

        elif intent == "GENERIC_CHAT":
            system_instructions += " Answer the user's question directly and supportively using your general knowledge."

        # 5. CONSTRUCT FINAL PRODUCTION PROMPT
        prompt = f"""
        {system_instructions}

        Previous Converation:
        {formatted_history}

        {"Context form Documents:" if context else ""}
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

            # NEW: SAVE TO CACHE FOR FUTURE USERS
            if intent in ['MATH', 'GENERIC_CHAT']:
                # Populate Tier 1 (Exact string map)
                local_redis_cache[cache_key] = full_response
                # Populate Tier 2 (MongoDB Vector Search index)
                save_to_semantic_cache(request.question, full_response)
                print(f" Saved to Cache: {request.question}")

        # Return a StreamingResponse instead of standard JSON dict
        return StreamingResponse(
            generate_streaming_response(),
            media_type="text/event-stream"
        )
    # ==================================================
    # PROPER ERROR HANDLING (Letting 403's pass through)
    # ==================================================
    except HTTPException as he:
        raise he
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