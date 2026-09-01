import os
import boto3
import pandas as pd
from typing import Dict, TypedDict, Any, Literal
from pydantic import BaseModel, Field, ValidationError
from botocore.config import Config
from botocore.exceptions import ClientError
from langgraph.graph import StateGraph, END
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

# Define the Pydantic Data Contract
class InvestigationDecision(BaseModel):
    """The strict schema the AI must adhere to."""
    reasoning: str = Field(
        description="A concise 2-sentence explanation of the cognitive thought process applying the strict mathematical rules."
    )
    decision: Literal["APPROVE", "BLOCK", "ESCALATE"] = Field(
        description="The final action based strictly on the decision matrix."
    )

# System Configuration & State
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(CURRENT_DIR, '../../data/fraudTrain.csv'))

class InvestigationState(TypedDict):
    transaction: Dict[str, Any]    
    historical_context: str        
    ai_reasoning: str              
    action_decision: str
    resolved_by: str     # "AI" or "HUMAN"        
    human_notes: str           

# Database & Engine Initialization
print("Booting Context Database Engine...")
try:
    historical_db = pd.read_csv(DB_PATH, usecols=['cc_num', 'amt', 'city', 'job'])
except FileNotFoundError:
    print(f"Critical Error: Could not locate historical database at {DB_PATH}")
    exit(1)

# Configure AWS Bedrock Client with Adaptive Retries
bedrock_config = Config(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive' 
    },
    connect_timeout=10,
    read_timeout=15
)

bedrock_client = boto3.client(
    service_name="bedrock-runtime",
    region_name="ap-southeast-1",
    config=bedrock_config
)

dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")
profiles_table = dynamodb.Table("finguard_profiles")

raw_llm = ChatBedrock(
    client=bedrock_client,
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    model_kwargs={"temperature": 0.0} 
)

structured_llm = raw_llm.with_structured_output(InvestigationDecision)

def human_control_node(state: InvestigationState) -> Dict[str, Any]:
    decision = state.get("action_decision", "PENDING")
    print(f"\n👤 [Human Authority] Analyst decision committed: {decision}")
    print(f"   Context: Case closed via manual operator override.\n")
    return {"resolved_by": "HUMAN"}

def auto_resolved_node(state: InvestigationState) -> Dict[str, Any]:
    print(f"\n🤖 [Autonomous Action] Engine executed: {state.get('action_decision')}")
    print(f"   Reasoning: {state.get('ai_reasoning')}\n")
    return {"resolved_by": "AI"}

# ---------------------------------------------------------
# The Nodes
# ---------------------------------------------------------
def context_builder_node(state: InvestigationState) -> Dict[str, Any]:
    """Data Fetching & Deterministic Math Calculation Node. No LLM inference here."""
    target_cc = state['transaction']['cc_num']
    current_amt = float(state['transaction']['amt'])
    current_city = state['transaction']['city']
    print(f"[Node: Context Builder] Querying historical truth for Card {target_cc}...")
    
    # 1. Primary Check: DynamoDB
    try:
        response = profiles_table.get_item(Key={"cc_num": target_cc})
        profile = response.get("Item")
        if profile:
            avg_amt = float(profile.get("avg_amt", 0))
            max_amt = float(profile.get("max_amt", 0))
            cities = profile.get("frequent_cities", [])
            job = profile.get("job", "Unknown")
            
            # Deterministic pre-calculation
            spend_multiplier = current_amt / max_amt if max_amt > 0 else 0
            is_new_city = current_city not in cities
            
            context = (
                f"User Profile (Source: DynamoDB): Employed as {job}. "
                f"Historical average transaction is ${avg_amt:.2f} (Max recorded: ${max_amt:.2f}). "
                f"Frequently transacts in these cities: {', '.join(cities)}. "
                f"SYSTEM CALCULATIONS: Current spend is {spend_multiplier:.1f}x the historical maximum. "
                f"New city flag: {is_new_city}."
            )
            return {"historical_context": context}
    except Exception as e:
        print(f"[Node: Context Builder] DynamoDB lookup skipped: {e}")

    # 2. Fallback: Historical CSV
    user_history = historical_db[historical_db['cc_num'] == target_cc]
    if user_history.empty:
        return {"historical_context": "No prior history exists for this user. Cold start."}
        
    avg_amt = user_history['amt'].mean()
    max_amt = user_history['amt'].max()
    common_cities = user_history['city'].value_counts().head(3).index.tolist()
    user_job = user_history['job'].iloc[0]
    
    # Deterministic pre-calculation
    spend_multiplier = current_amt / max_amt if max_amt > 0 else 0
    is_new_city = current_city not in common_cities
    
    context = (
        f"User Profile (Source: Historical CSV): Employed as {user_job}. "
        f"Historical average transaction is ${avg_amt:.2f} (Max recorded: ${max_amt:.2f}). "
        f"Frequently transacts in these cities: {', '.join(common_cities)}. "
        f"SYSTEM CALCULATIONS: Current spend is {spend_multiplier:.1f}x the historical maximum. "
        f"New city flag: {is_new_city}."
    )
    return {"historical_context": context}

def reasoning_agent(state: InvestigationState) -> Dict[str, Any]:
    print("[Agent: Reasoning] Executing deterministic cognitive analysis via AWS Bedrock...")
    
    # The prompt is now a rigid mathematical matrix, eliminating subjective hallucination
    system_prompt = """You are a Tier 2 Fraud Investigation AI.
You operate strictly as a logic gate. Analyze the transaction data and context provided. 
You must rigidly apply the following mathematical decision matrix:

- APPROVE: Transaction amount is <= 1.5x their historical maximum AND New city flag is False.
- BLOCK: Transaction amount is > 3.0x their historical maximum OR velocity score is > 5.0.
- ESCALATE: Cold start users (no prior history), OR transaction amount is between 1.5x and 3.0x, OR New city flag is True.

Do not guess. Execute the logic. Use the provided schema to output your decision."""

    human_prompt = f"""
    Transaction Data (Flagged by Tier 1): {state['transaction']}
    Historical Context: {state['historical_context']}
    """

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    try:
        result = structured_llm.invoke(messages)
        return {
            "ai_reasoning": result.reasoning,
            "action_decision": result.decision
        }
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "ClientError")
        print(f"[System Failsafe] AWS Bedrock ClientError ({error_code}): {e}")
        return {
            "ai_reasoning": f"System Failsafe (AWS Bedrock {error_code}): Upstream rate limit or API failure. Escalating for human review.",
            "action_decision": "ESCALATE"
        }
    except ValidationError as e:
        print(f"[System Failsafe] Schema validation failed: {e}")
        return {
            "ai_reasoning": "System Failsafe (Schema Validation): AI output failed to adhere to strict Pydantic data schema.",
            "action_decision": "ESCALATE"
        }
    except Exception as e:
        error_str = str(e)
        print(f"[System Failsafe] Upstream failure: {error_str}")
        if "ThrottlingException" in error_str or "Too many requests" in error_str:
            reason = "System Failsafe (AWS Bedrock Throttling): Rate limit reached (RPM quota exceeded). Escalating for manual review."
        else:
            reason = f"System Failsafe (Runtime Exception): {error_str[:120]}..."
            
        return {
            "ai_reasoning": reason,
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
def build_investigator_graph(memory=None):
    workflow = StateGraph(InvestigationState)

    # Note the updated node name here
    workflow.add_node("Context_Builder", context_builder_node)
    workflow.add_node("Cognitive_Engine", reasoning_agent)
    workflow.add_node("Human_Control_Center", human_control_node)
    workflow.add_node("System_Resolved", auto_resolved_node)

    workflow.set_entry_point("Context_Builder")
    workflow.add_edge("Context_Builder", "Cognitive_Engine")
    
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
    
    if memory is not None:
        return workflow.compile(
            checkpointer=memory, 
            interrupt_before=["Human_Control_Center"]
        )
    return workflow.compile()