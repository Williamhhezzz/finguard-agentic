import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import os

# System Configuration
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))       
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '../..')) 

DATA_PATH = os.path.join(PROJECT_ROOT, 'data', 'fraudTrain.csv')
MODEL_DIR = os.path.join(CURRENT_DIR, 'artifacts')

def engineer_features(df):
    print("Engineering temporal and spatial features...")
    
    # Enforce chronological truth
    df['trans_date_trans_time'] = pd.to_datetime(df['trans_date_trans_time'])
    df = df.sort_values(by=['cc_num', 'trans_date_trans_time'])
    
    # Calculate Delta T (Time since last transaction) in seconds
    df['prev_time'] = df.groupby('cc_num')['trans_date_trans_time'].shift(1)
    df['delta_t'] = (df['trans_date_trans_time'] - df['prev_time']).dt.total_seconds()
    
    # Calculate Delta D (Proxy for physical distance via Euclidean shift)
    df['prev_lat'] = df.groupby('cc_num')['lat'].shift(1)
    df['prev_long'] = df.groupby('cc_num')['long'].shift(1)
    df['delta_d'] = np.sqrt((df['lat'] - df['prev_lat'])**2 + (df['long'] - df['prev_long'])**2)
    
    # Fill absolute nulls (the first transaction for every card has no history)
    df['delta_t'] = df['delta_t'].fillna(0)
    df['delta_d'] = df['delta_d'].fillna(0)
    
    # Calculate Velocity (Distance / Time) - add small epsilon to prevent division by zero
    df['velocity'] = df['delta_d'] / (df['delta_t'] + 1e-5)
    
    return df

def train_tier_1_model():
    print(f"Loading historical truth from {DATA_PATH}...")
    df = pd.read_csv(DATA_PATH)
    
    # Process Features
    df = engineer_features(df)
    
    # Define Target and Features (simplified for architectural testing)
    features = ['amt', 'lat', 'long', 'city_pop', 'delta_t', 'delta_d', 'velocity']
    X = df[features]
    y = df['is_fraud']
    
    # Split the dataset
    print("Splitting dataset into training and validation folds...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # Calculate the exact mathematical imbalance
    legit_count = len(y_train[y_train == 0])
    fraud_count = len(y_train[y_train == 1])
    imbalance_ratio = legit_count / fraud_count
    print(f"Calculated scale_pos_weight: {imbalance_ratio:.2f}")
    
    # Initialize the XGBoost Engine
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        scale_pos_weight=imbalance_ratio,
        random_state=42,
        eval_metric='logloss'
    )
    
    # Train the Model
    print("Initiating XGBoost training sequence...")
    model.fit(X_train, y_train)
    
    # Validate the Model
    print("\nModel Validation Report:")
    predictions = model.predict(X_test)
    print(classification_report(y_test, predictions))
    
    # Serialize the Model
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_DIR, 'tier1_xgboost.json')
    model.save_model(model_path)
    print(f"✅ Tier 1 Model successfully forged and serialized to {model_path}")

if __name__ == '__main__':
    train_tier_1_model()