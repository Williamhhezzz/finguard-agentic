from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver
from agents.investigator import build_investigator_graph
from typing import Dict, Any

# Initialize the API Server
app = FastAPI(title="FinGuard Agentic API")

# Attach the LangGraph Checkpointer (State Persistence)
memory = MemorySaver()

# Pass the memory directly into the builder
graph = build_investigator_graph(memory=memory)

# Data Contracts for the API
class TransactionPayload(BaseModel):
    transaction_id: str
    cc_num: int
    amt: float
    city: str
    job: str
    velocity: float

class HumanDecision(BaseModel):
    decision: str  # "APPROVE" or "BLOCK"

# The API Endpoints
@app.post("/api/investigate")
async def trigger_investigation(payload: TransactionPayload):
    """Ingests a transaction and starts the cognitive engine."""
    
    # We assign a unique thread_id to this specific investigation
    config = {"configurable": {"thread_id": payload.transaction_id}}
    
    # Run the graph
    print(f"\n[API] Initiating investigation for Thread: {payload.transaction_id}")
    graph.invoke({"transaction": payload.model_dump()}, config)
    
    # Check if the graph paused (escalated) or finished (auto-resolved)
    state = graph.get_state(config)
    if not state.next:
        return {"status": "auto_resolved", "final_state": state.values}
    else:
        return {"status": "escalated_to_human", "reasoning": state.values.get("ai_reasoning")}

@app.get("/api/escalations")
async def get_pending_escalations():
    """Next.js will poll this endpoint to populate the UI Queue."""
    return {"message": "Endpoint alive. Ready to serve queue."}

@app.post("/api/resolve/{transaction_id}")
async def resolve_escalation(transaction_id: str, human_input: HumanDecision):
    """Receives the human click from Next.js and resumes the graph."""
    config = {"configurable": {"thread_id": transaction_id}}
    
    state = graph.get_state(config)
    if not state.next:
        raise HTTPException(status_code=400, detail="No pending escalation for this transaction.")
    
    print(f"[API] Human override received for {transaction_id}: {human_input.decision}")
    
    # Inject the human decision into the state and resume the graph
    graph.update_state(config, {"action_decision": human_input.decision})
    graph.invoke(None, config)
    
    return {"status": "resolved", "final_decision": human_input.decision}