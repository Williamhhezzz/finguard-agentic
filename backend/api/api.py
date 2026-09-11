import os
import boto3
from decimal import Decimal
from typing import Dict, Any
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.checkpoint.memory import MemorySaver
from agents.investigator import build_investigator_graph

app = FastAPI(title="FinGuard Agentic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to AWS DynamoDB
dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")
escalations_table = dynamodb.Table("finguard_escalations")
profiles_table = dynamodb.Table("finguard_profiles")

# In-memory graph builder
memory = MemorySaver()
graph = build_investigator_graph(memory=memory)

class TransactionPayload(BaseModel):
    transaction_id: str
    cc_num: int
    amt: float
    city: str
    job: str
    velocity: float

class HumanDecision(BaseModel):
    decision: str  # "APPROVE" or "BLOCK"

def convert_floats_to_decimals(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_floats_to_decimals(i) for i in obj]
    return obj

def update_user_profile_dynamo(cc_num: int, amt: float, city: str, job: str):
    """Updates or creates the user's historical baseline in DynamoDB."""
    try:
        response = profiles_table.get_item(Key={"cc_num": cc_num})
        profile = response.get("Item")

        if not profile:
            profiles_table.put_item(
                Item={
                    "cc_num": cc_num,
                    "job": job,
                    "total_spend": Decimal(str(amt)),
                    "txn_count": 1,
                    "avg_amt": Decimal(str(amt)),
                    "max_amt": Decimal(str(amt)),
                    "frequent_cities": [city],
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
            )
        else:
            new_count = profile.get("txn_count", 0) + 1
            new_total = profile.get("total_spend", Decimal("0")) + Decimal(str(amt))
            new_avg = round(new_total / new_count, 2)
            current_max = profile.get("max_amt", Decimal("0"))
            new_max = max(current_max, Decimal(str(amt)))

            cities = profile.get("frequent_cities", [])
            if city not in cities:
                cities.append(city)
                cities = cities[-5:]

            profiles_table.update_item(
                Key={"cc_num": cc_num},
                UpdateExpression="SET txn_count = :cnt, total_spend = :tot, avg_amt = :avg, max_amt = :max, frequent_cities = :cities, last_updated = :ts",
                ExpressionAttributeValues={
                    ":cnt": new_count,
                    ":tot": new_total,
                    ":avg": new_avg,
                    ":max": new_max,
                    ":cities": cities,
                    ":ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        print(f"[DynamoDB] Profile baseline updated for Card {cc_num}")
    except Exception as e:
        print(f"[DynamoDB Warning] Failed to update user profile: {e}")

@app.get("/api/metrics")
async def get_system_metrics():
    """Aggregates real-time throughput, AI routing, and HITL metrics from DynamoDB."""
    try:
        response = escalations_table.scan()
        items = response.get("Items", [])
        
        tier2_total = len(items)
        auto_resolved_ai = sum(1 for i in items if i.get("resolved_by") == "AI")
        human_resolved = sum(1 for i in items if i.get("resolved_by") == "HUMAN")
        
        pending_human = sum(
            1 for i in items 
            if i.get("status") == "PENDING_HUMAN_REVIEW" and i.get("resolved_by") == "PENDING"
        )
        
        total_escalated_human = human_resolved + pending_human
        total_blocked = sum(1 for i in items if i.get("decision") == "BLOCK")
        total_approved = sum(1 for i in items if i.get("decision") == "APPROVE")
        
        return {
            "tier2_total": tier2_total,
            "auto_resolved_ai": auto_resolved_ai,
            "human_resolved": human_resolved,
            "total_escalated_human": total_escalated_human,
            "pending_human_review": pending_human,
            "total_approved": total_approved,
            "total_blocked": total_blocked,
        }
    except Exception as e:
        print(f"[Metrics Warning] Failed to aggregate metrics: {e}")
        return {
            "tier2_total": 0, "auto_resolved_ai": 0, "human_resolved": 0,
            "total_escalated_human": 0, "pending_human_review": 0,
            "total_approved": 0, "total_blocked": 0,
        }

@app.post("/api/investigate")
async def trigger_investigation(payload: TransactionPayload):
    txn_dict = payload.model_dump()
    thread_id = payload.transaction_id
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n[API] Initiating async investigation for Thread: {thread_id}")
    await graph.ainvoke({"transaction": txn_dict}, config)

    state = graph.get_state(config)
    
    if not state.next:
        decision = state.values.get("action_decision", "APPROVE")
        
        if decision == "APPROVE":
            update_user_profile_dynamo(
                cc_num=payload.cc_num, amt=payload.amt, city=payload.city, job=payload.job
            )

        escalations_table.put_item(
            Item={
                "thread_id": thread_id,
                "status": "AUTO_RESOLVED",
                "decision": decision,
                "transaction": convert_floats_to_decimals(txn_dict),
                "ai_reasoning": state.values.get("ai_reasoning", ""),
                "resolved_by": "AI",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {"status": "auto_resolved", "final_state": state.values}
    else:
        reasoning = state.values.get("ai_reasoning", "Escalated for human oversight.")
        escalations_table.put_item(
            Item={
                "thread_id": thread_id,
                "status": "PENDING_HUMAN_REVIEW",
                "transaction": convert_floats_to_decimals(txn_dict),
                "ai_reasoning": reasoning,
                "resolved_by": "PENDING",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {"status": "escalated_to_human", "reasoning": reasoning}

@app.get("/api/escalations")
async def get_pending_escalations():
    response = escalations_table.scan(
        FilterExpression="attribute_not_exists(#res) OR #res = :pending",
        ExpressionAttributeNames={"#res": "resolved_by"},
        ExpressionAttributeValues={":pending": "PENDING"},
    )
    
    items = response.get("Items", [])
    formatted_escalations = {
        item["thread_id"]: {
            "transaction": item.get("transaction", {}),
            "reasoning": item.get("ai_reasoning", ""),
            "timestamp": item.get("timestamp", ""),
        }
        for item in items
    }
    return {"escalations": formatted_escalations}

@app.post("/api/resolve/{thread_id}")
async def resolve_escalation(thread_id: str, request: HumanDecision):
    """Unified resolution endpoint with memory-wipe failsafe."""
    config = {"configurable": {"thread_id": thread_id}}
    decision = request.decision.upper()
    txn_data = {}
    
    try:
        # 1. Try to resume the LangGraph thread in memory
        state = graph.get_state(config)
        if state.next:
            graph.update_state(
                config,
                {"action_decision": decision, "resolved_by": "HUMAN", "human_notes": f"Manual override: {decision}"},
                as_node="Human_Control_Center",
            )
            await graph.ainvoke(None, config)
            txn_data = state.values.get("transaction", {})
            print(f"[API] LangGraph thread {thread_id} resumed and resolved.")
    except Exception as e:
        # 2. FAILSAFE: If server restarted and RAM was wiped, bypass LangGraph and fetch from DB
        print(f"[System Failsafe] Memory thread missing for {thread_id}. Resolving via DynamoDB directly.")
        esc_item = escalations_table.get_item(Key={"thread_id": thread_id}).get("Item", {})
        txn_data = esc_item.get("transaction", {})

    # 3. If Approved, update user baseline profile
    if decision == "APPROVE" and txn_data:
        update_user_profile_dynamo(
            cc_num=int(txn_data.get("cc_num", 0)),
            amt=float(txn_data.get("amt", 0)),
            city=txn_data.get("city", ""),
            job=txn_data.get("job", "")
        )

    # 4. Mark as resolved in DynamoDB
    escalations_table.update_item(
        Key={"thread_id": thread_id},
        UpdateExpression="SET #res = :res, #dec = :dec, #s = :status",
        ExpressionAttributeNames={
            "#res": "resolved_by",
            "#dec": "decision",
            "#s": "status"
        },
        ExpressionAttributeValues={
            ":res": "HUMAN",
            ":dec": decision,
            ":status": "RESOLVED",
        },
    )

    return {"status": "resolved", "final_decision": decision}