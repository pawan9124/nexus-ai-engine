# Question: Why are we using the function 'search_company_documents' in our RAG workflow when we even not coding it?

Answer: `Here is exactly what would happen if you asked, "Summarize the System Design PDF"

The question hits the Agent Node.

The Agent looks at its tools and says, "I only have a check_billing_status tool. I don't need that. I'll just answer the question normally."

The Router sees no tool was requested, so it sends the train straight to the Generate Node.

💥 THE CRASH: The Generate Node runs, looks inside your GraphState for the documents array... and finds nothing.

**If we had added `search_company_documents` to the `ToolNode`:**

The Agent would say, "Ah! I see I have a search_company_documents tool. Let me request to use that." The LangGraph server would see that request and immediately execute the Python code you wrote in `tools.py`, injecting the results into the `documents` field of your state."