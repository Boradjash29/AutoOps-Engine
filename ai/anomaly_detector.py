# FILE: ai/anomaly_detector.py
import numpy as np
from sklearn.ensemble import IsolationForest
import pickle
import os
import logging

MODEL_PATH = "logs/anomaly_model.pkl"

class AnomalyDetector:
    def __init__(self, contamination: float = 0.05):
        self.model = IsolationForest(
            n_estimators=100,
            contamination=contamination,
            random_state=42
        )
        self.is_trained = False
        self.feature_names = ["cpu", "ram", "disk"]
        self.load()

    def train(self, data: list[dict]) -> bool:
        if len(data) < 50:
            logging.warning("Insufficient data to train AnomalyDetector (need at least 50).")
            return False
            
        features = []
        for row in data:
            if 'cpu' in row and 'ram' in row and 'disk' in row:
                features.append([row['cpu'], row['ram'], row['disk']])
                
        if len(features) < 50:
            return False
            
        X = np.array(features)
        self.model.fit(X)
        self.is_trained = True
        logging.info(f"Anomaly model trained on {len(X)} samples.")
        return True

    def load(self) -> bool:
        if os.path.exists(MODEL_PATH):
            try:
                with open(MODEL_PATH, "rb") as f:
                    self.model = pickle.load(f)
                self.is_trained = True
                logging.info("Anomaly model loaded successfully.")
                return True
            except Exception as e:
                logging.error(f"Failed to load anomaly model: {e}")
        return False

    def predict(self, cpu: float, ram: float, disk: float) -> dict:
        if not self.is_trained:
            return {"is_anomaly": False, "score": 0.0, "confidence": 0.0}
            
        X = np.array([[cpu, ram, disk]])
        # decision_function returns negative for anomalies, positive for normal
        score = float(self.model.decision_function(X)[0])
        is_anomaly = score < 0
        
        # normalize confidence between 0 and 1
        confidence = min(abs(score) / 0.5, 1.0)
        
        return {
            "is_anomaly": is_anomaly,
            "score": score,
            "confidence": confidence
        }

    def save(self):
        if self.is_trained:
            try:
                with open(MODEL_PATH, "wb") as f:
                    pickle.dump(self.model, f)
                logging.info("Anomaly model saved successfully.")
            except Exception as e:
                logging.error(f"Failed to save anomaly model: {e}")
