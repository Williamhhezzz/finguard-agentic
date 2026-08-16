import json
import os
import requests
import xgboost as xgb
import pandas as pd
import math
from confluent_kafka import Consumer, KafkaError

# 1. Environment & Path Resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '../..'))
MODEL_PATH = os.path.join(PROJECT_ROOT, 'backend', 'ml', 'artifacts', 'tier1_xgboost.json')

KAFKA_BROKER = 'localhost:9092'
TOPIC_NAME = 'finguard-all-events'
API_INVESTIGATE_URL = 'http://localhost:8000/api/investigate'

# 2. Load Tier 1 ML Model (XGBoost)
print("[Tier 1 Worker] Loading serialized XGBoost booster...")
booster = xgb.Booster()
booster.load_model(MODEL_PATH)
print("✅ XGBoost booster loaded successfully.")

# Exact feature order required by your trained model
FEATURE_COLUMNS = ['amt', 'lat', 'long', 'city_pop', 'delta_t', 'delta_d', 'velocity']

# Local State Memory (Simulating Spark Structured Streaming state store)
cc_state = {}

def preprocess_and_score(payload: dict) -> float:
    """Extracts stateful features and predicts fraud probability."""
    cc_num = payload.get('cc_num')
    current_time = payload.get('unix_time', 0)
    lat = payload.get('lat', 0.0)
    lon = payload.get('long', 0.0)
    
    # Stateful Feature Engineering
    delta_t = 0.0
    delta_d = 0.0
    velocity = 1.0

    if cc_num in cc_state:
        prev = cc_state[cc_num]
        delta_t = float(current_time - prev['time'])
        # Simplified Euclidean distance for MVP delta_d
        delta_d = math.sqrt((lat - prev['lat'])**2 + (lon - prev['long'])**2)
        velocity = prev['count'] + 1
    
    # Update rolling state
    cc_state[cc_num] = {
        'time': current_time,
        'lat': lat,
        'long': lon,
        'count': velocity
    }
    
    # Construct exact payload for XGBoost
    features = {
        'amt': payload.get('amt', 0.0),
        'lat': lat,
        'long': lon,
        'city_pop': payload.get('city_pop', 0),
        'delta_t': delta_t,
        'delta_d': delta_d,
        'velocity': velocity
    }
    
    # Enforce exact column ordering
    df_features = pd.DataFrame([features])[FEATURE_COLUMNS]
    dmatrix = xgb.DMatrix(df_features)
    
    return float(booster.predict(dmatrix)[0])

def start_consumer():
    conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'group.id': 'finguard-tier1-group',
        'auto.offset.reset': 'latest',
        'enable.auto.commit': True
    }
    
    consumer = Consumer(conf)
    consumer.subscribe([TOPIC_NAME])
    print(f"🚀 [Tier 1 Ingestion Worker] Subscribed to '{TOPIC_NAME}'. Listening for events...\n")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() in [KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART]:
                    continue
                else:
                    print(f"❌ Kafka Error: {msg.error()}")
                    break

            raw_data = msg.value().decode('utf-8')
            payload = json.loads(raw_data)
            
            txn_id = payload.get('trans_num', f"txn_{payload.get('unix_time', 'unknown')}")
            cc_num = payload.get('cc_num', 0)
            amt = payload.get('amt', 0.0)
            
            try:
                prob = preprocess_and_score(payload)
                print(f"[Tier 1 Inference] Txn: {txn_id} | Amount: ${amt:.2f} | Risk Score: {prob:.4f}")

                if prob < 0.20:
                    print(f"   🟢 Auto-Approved (Risk < 0.20)")
                elif prob > 0.90:
                    print(f"   🔴 Auto-Blocked (Risk > 0.90)")
                else:
                    print(f"   ⚠️ Ambiguous Anomaly ({prob:.2f}) -> Dispatching to Tier 2 Cognitive Engine...")
                    
                    investigation_payload = {
                        "transaction_id": str(txn_id),
                        "cc_num": int(cc_num),
                        "amt": float(amt),
                        "city": str(payload.get('city', 'Unknown')),
                        "job": str(payload.get('job', 'Unknown')),
                        "velocity": float(cc_state.get(cc_num, {}).get('count', 1.0))
                    }
                    
                    response = requests.post(API_INVESTIGATE_URL, json=investigation_payload, timeout=30)
                    if response.status_code == 200:
                        print(f"   📬 Dispatched to Tier 2 Agent. Response: {response.json().get('status')}")
                    else:
                        print(f"   ⚠️ Tier 2 Dispatch Failed: HTTP {response.status_code}")
            except Exception as e:
                print(f"❌ Pipeline Failure on txn {txn_id}: {e}")

    except KeyboardInterrupt:
        print("\n🛑 Stopping Tier 1 Worker...")
    finally:
        consumer.close()

if __name__ == '__main__':
    start_consumer()