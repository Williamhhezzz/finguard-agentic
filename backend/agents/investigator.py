import os
import pandas as pd
from typing import Dict, TypedDict, Any, Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

# Define the Pydantic Data Contract
class InvestigationDecision(BaseModel):
    """The strict schema the AI must adhere to."""
    reasoning: str = Field(
        description="A concise 2-sentence explanation of the cognitive thought process."
    )
    decision: Literal["APPROVE", "BLOCK", "ESCALATE"] = Field(
        description="The final action. ESCALATE for ambiguity, BLOCK for severe deviation, APPROVE for normal behavior."
    )

# System Configuration & State
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(CURRENT_DIR, '../../data/fraudTrain.csv'))

class InvestigationState(TypedDict):
    transaction: Dict[str, Any]    
    historical_context: str        
    ai_reasoning: str              
    action_decision: str           

# Database & Engine Initialization
print("Booting Context Database Engine...")
try:
    historical_db = pd.read_csv(DB_PATH, usecols=['cc_num', 'amt', 'city', 'job'])
except FileNotFoundError:
    print(f"Critical Error: Could not locate historical database at {DB_PATH}")
    exit(1)

# Initialize the Bedrock Engine
raw_llm = ChatBedrock(
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    region_name="ap-southeast-1",
    model_kwargs={"temperature": 0.0} 
)

# Bind the Pydantic schema directly to the AI Engine
structured_llm = raw_llm.with_structured_output(InvestigationDecision)

# ---------------------------------------------------------
# The Agents (Nodes)
# ---------------------------------------------------------
def context_agent(state: InvestigationState) -> Dict[str, Any]:
    target_cc = state['transaction']['cc_num']
    print(f"[Agent: Context] Querying historical truth for Card {target_cc}...")
    
    user_history = historical_db[historical_db['cc_num'] == target_cc]
    
    if user_history.empty:
        return {"historical_context": "No prior history exists for this user. Cold start. Treat with high suspicion."}
        
    avg_amt = user_history['amt'].mean()
    max_amt = user_history['amt'].max()
    common_cities = user_history['city'].value_counts().head(3).index.tolist()
    user_job = user_history['job'].iloc[0]
    
    context = (
        f"User Profile: Employed as {user_job}. "
        f"Historical average transaction is ${avg_amt:.2f} (Max recorded: ${max_amt:.2f}). "
        f"Frequently transacts in these cities: {', '.join(common_cities)}."
    )
    return {"historical_context": context}

def reasoning_agent(state: InvestigationState) -> Dict[str, Any]:
    print("[Agent: Reasoning] Executing cognitive analysis via AWS Bedrock...")
    
    system_prompt = """You are a Tier 2 Fraud Investigation AI. 
    Analyze the transaction against the user's historical context.
    Use the provided tool to output your final decision."""

    human_prompt = f"""
    Transaction Data (Flagged by Tier 1): {state['transaction']}
    Historical Context: {state['historical_context']}
    """

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    # The output is now guaranteed to be a verified Pydantic object
    try:
        result = structured_llm.invoke(messages)
        return {
            "ai_reasoning": result.reasoning,
            "action_decision": result.decision
        }
    except Exception as e:
        print(f"[System Failsafe] Structured output rejected: {e}")
        return {
            "ai_reasoning": "System Failsafe: AI failed to adhere to strict Pydantic data schema.",
            "action_decision": "ESCALATE"
        }

# ---------------------------------------------------------
# Routing Logic (Edges)
# ---------------------------------------------------------
def hitl_router(state: InvestigationState) -> Literal["human_review", "auto_resolve"]:
    decision = state["action_decision"]
    if decision == "ESCALATE":
        print(f"[Router] Ambiguity detected. Escaping to Human Control Center. Reason: {state['ai_reasoning']}")
        return "human_review"
    else:
        print(f"[Router] High confidence logic achieved. Auto-executing {decision}. Reason: {state['ai_reasoning']}")
        return "auto_resolve"

# Graph Compilation
def build_investigator_graph():
    workflow = StateGraph(InvestigationState)

    workflow.add_node("Context_Gatherer", context_agent)
    workflow.add_node("Cognitive_Engine", reasoning_agent)
    workflow.add_node("Human_Control_Center", lambda state: print("🚨 GRAPH PAUSED: Awaiting human input via dashboard..."))
    workflow.add_node("System_Resolved", lambda state: print("✅ Threat neutralized or dismissed autonomously."))

    workflow.set_entry_point("Context_Gatherer")
    workflow.add_edge("Context_Gatherer", "Cognitive_Engine")
    
    workflow.add_conditional_edges(
        "Cognitive_Engine",
        hitl_router,
        {
            "human_review": "Human_Control_Center",
            "auto_resolve": "System_Resolved"
        }
    )

    workflow.add_edge("Human_Control_Center", END)
    workflow.add_edge("System_Resolved", END)

    return workflow.compile()

if __name__ == "__main__":
    test_transaction = {
        "cc_num": 229116389427, 
        "amt": 4500.00,
        "city": "London",
        "job": "Software Engineer",
        "velocity": 950.5 
    }
    
    print("\nInitiating Tier 2 Cognitive Engine...")
    graph = build_investigator_graph()
    graph.invoke({"transaction": test_transaction})