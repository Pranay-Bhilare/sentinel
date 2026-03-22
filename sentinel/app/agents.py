import os
from langchain_groq import ChatGroq

from app.tools import INVESTIGATOR_TOOLS, OPERATOR_TOOLS

def get_investigator_model():
    """Returns ChatGroq bound with tools for deep code RCA (Trace + Code)."""
    model = ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
    return model.bind_tools(INVESTIGATOR_TOOLS)

def get_operator_model():
    """Returns ChatGroq bound with infrastructure remediation tools."""
    model = ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
    return model.bind_tools(OPERATOR_TOOLS)
