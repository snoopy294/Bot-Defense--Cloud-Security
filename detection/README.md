# detection/ — ML bot-vs-human classifier (Phase 5)

Reuses the Log-Anomaly-Detector approach: feature extraction from request logs, **leak-safe splits**
(zero entity overlap across train/val/test), a trained classifier, and a real-time scoring Lambda.
Trained on the labeled traffic captured in Phase 4. Built in Phase 5.
