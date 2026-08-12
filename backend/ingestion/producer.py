import json
import time
import pandas as pd
from confluent_kafka import Producer

# System Configuration
KAFKA_BROKER = 'localhost:9092' 
TOPIC_NAME = 'finguard-all-events'
DATA_PATH = '../../data/fraudTest.csv'

def delivery_report(err, msg):
    """
    The Callback Protocol: Called once for each message produced to indicate delivery result.
    This enforces radical transparency in the data pipeline.
    """
    if err is not None:
        print(f"❌ Message delivery failed: {err}")
    else:
        print(f"✅ Message delivered to {msg.topic()} [Partition: {msg.partition()}]")

def stream_data():
    # Initialize the Kafka Producer
    print("Booting Ingestion Engine...")
    producer_conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'client.id': 'finguard-python-producer'
        # Future: AWS MSK IAM authentication configurations will be added here
    }
    producer = Producer(producer_conf)

    # Load the simulated stream payload
    print(f"Loading data payload from {DATA_PATH}...")
    try:
        df = pd.read_csv(DATA_PATH)
    except FileNotFoundError:
        print(f"Critical Error: Could not locate data at {DATA_PATH}.")
        return

    # Execute the Streaming Sequence
    print("Initiating real-time streaming sequence...")
    for index, row in df.iterrows():
        # Transform the static CSV row into a dynamic JSON event
        transaction = row.to_dict()
        payload = json.dumps(transaction)
        
        # Define the routing key
        partition_key = str(transaction.get('cc_num', 'unknown'))

        # Asynchronously push the event to the Kafka Broker
        producer.produce(
            topic=TOPIC_NAME,
            key=partition_key,
            value=payload,
            callback=delivery_report
        )
        
        # Trigger any available delivery report callbacks from previous loops
        producer.poll(0)
        
        # Throttle the loop to simulate real-time human behavior (e.g., 0.5 seconds between swipes)
        time.sleep(0.5)

    # Force the engine to wait until all inflight messages are mathematically confirmed
    print("Flushing final events...")
    producer.flush()
    print("Streaming sequence complete.")

if __name__ == '__main__':
    stream_data()