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

# In-memory graph builder (immediate thread state, long-term persistence handled via DynamoDB)
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

# Helper to serialize Python floats to DynamoDB Decimals
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
            # First-time profile initialization in the cloud
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
            # Incrementally update spending metrics to prevent concept drift
            new_count = profile.get("txn_count", 0) + 1
            new_total = profile.get("total_spend", Decimal("0")) + Decimal(str(amt))
            new_avg = round(new_total / new_count, 2)
            current_max = profile.get("max_amt", Decimal("0"))
            new_max = max(current_max, Decimal(str(amt)))

            cities = profile.get("frequent_cities", [])
            if city not in cities:
                cities.append(city)
                cities = cities[-5:]  # Retain the 5 most recent cities

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
                cc_num=payload.cc_num,
                amt=payload.amt,
                city=payload.city,
                job=payload.job
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

@app.post("/api/resolve/{transaction_id}")
async def resolve_escalation(transaction_id: str, human_input: HumanDecision):
    config = {"configurable": {"thread_id": transaction_id}}
    
    state = graph.get_state(config)
    if not state.next:
        raise HTTPException(status_code=400, detail="No active graph state found for this thread.")

    graph.update_state(
        config,
        {
            "action_decision": human_input.decision,
            "resolved_by": "HUMAN",
            "human_notes": f"Manual override: {human_input.decision}",
        },
        as_node="Human_Control_Center",
    )
    await graph.ainvoke(None, config)

    if human_input.decision == "APPROVE":
        txn = state.values.get("transaction", {})
        update_user_profile_dynamo(
            cc_num=txn.get("cc_num"),
            amt=float(txn.get("amt", 0)),
            city=txn.get("city", ""),
            job=txn.get("job", "")
        )

    escalations_table.update_item(
        Key={"thread_id": transaction_id},
        UpdateExpression="SET #res = :res, #dec = :dec, #res_at = :res_at",
        ExpressionAttributeNames={
            "#res": "resolved_by",
            "#dec": "decision",
            "#res_at": "resolved_at",
        },
        ExpressionAttributeValues={
            ":res": "HUMAN",
            ":dec": human_input.decision,
            ":res_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {"status": "resolved", "final_decision": human_input.decision}