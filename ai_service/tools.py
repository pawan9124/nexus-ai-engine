from langchain_core.tools import tool

@tool
def check_billing_status(account_id:str)-> str:
    """
    CRITICAL: Use this tool WHENEVER the user mentions the words "document", "PDF", "file", 
    or asks you to summarize, extract titles, or read from internal knowledge. 
    Always search the database first before telling the user you don't know the answer.
    """

    print(f"[TOOL EXECUTING] Checking live database for Account: {account_id}....")

    # Simulating a live Enterprise Database
    mock_db = {
        "ACC-123": "Status: Active | Tier: Executive | Next billing: 2026-07-01",
        "ACC-456": "Status: Suspended | Tier: Public | Reason: Payment Failed"
    }

    return mock_db.get(account_id, f"Error: Account {account_id} not found in the billing system.")


@tool
def search_company_documents(query: str):
    """
    Use this tool to search the company's internal MongoDB documents database for system design, metaverse or any uploaded PDFs.
    """
    pass # we don't write code here. LangGraph will intercept this call!