# FILE: ai/trainer.py
import threading
import time
import logging
from api.database import get_history

class ModelTrainer:
    def __init__(self, detector):
        self.detector = detector
        self.running = False
        self._thread = None

    def start(self):
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._train_loop, daemon=True)
            self._thread.start()

    def _train_loop(self):
        # On first run, check if we need immediate training
        if not self.detector.is_trained:
            data = get_history(limit=2000)
            if self.detector.train(data):
                self.detector.save()
            else:
                # Wait a bit if not enough data yet
                time.sleep(600)
                
        while self.running:
            # Wait 60 minutes
            time.sleep(3600)
            if not self.running:
                break
                
            try:
                data = get_history(limit=2000)
                if self.detector.train(data):
                    self.detector.save()
            except Exception as e:
                logging.error(f"Error in ModelTrainer loop: {e}")
