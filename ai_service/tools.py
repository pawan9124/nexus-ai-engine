import requests
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

@tool
def issue_customer_refund(account_id:str, amount:int) -> str:
    """
    CRITICAL: Use this tool to issue monetary refund to a customre.
    This is highly sensitve action.
    """
    print(f" [DANGEROUS TOOL EXECUTING] Issuing ${amount} refund to {account_id}...")
    return f"Success: ${amount} has been refunded to {account_id}"

@tool 
def get_live_weather(latitude:float, longitude:float) -> str:
    """
    Fetches the current real-world weather temperature for a specific location.
    You must provide the latitude and longitude as floats. Use you general knowledge to estimate the coordinates for the requsted city.
    """

    print(f" [LIVE API CALL] Fetching weather for lat:{latitude}&longitude={longitude}...")

    url =  f'https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true'

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        current_temp = data['current_weather']['temperature']
        wind_speed = data['current_weather']['windspeed']

        return  f"The current temperature is {current_temp}*C with a wind speed of {wind_speed}km/h."
    except Exception as e:
        return f"Failed to fetch live weather data: {str(e)}"


