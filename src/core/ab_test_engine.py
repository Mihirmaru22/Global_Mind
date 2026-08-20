"""
A/B Testing Framework for Prompt Optimization
Enables scientific testing of prompt variants with statistical significance analysis.
"""
import json
import os
import logging
import hashlib
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

EXPERIMENT_LOG_PATH = "data/experiment_logs.jsonl"
EXPERIMENTS_CONFIG_PATH = "config/experiments.yaml"


@dataclass
class ExperimentEvent:
    experiment_id: str
    user_id: str
    variant: str  # control, variant_a, variant_b
    query: str
    success: bool
    latency_ms: float
    confidence_score: float
    reflexion_count: int
    timestamp: str


class ABTestEngine:
    """Manages A/B tests for prompt variants with statistical analysis."""
    
    def __init__(self, config_path: str = EXPERIMENTS_CONFIG_PATH):
        self.config_path = config_path
        self.experiments: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """Load experiment configuration from YAML file."""
        import yaml
        
        if not os.path.exists(self.config_path):
            logger.warning(f"Experiment config not found at {self.config_path}")
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.experiments = yaml.safe_load(f) or {}
            logger.info(f"Loaded {len(self.experiments)} experiment configurations")
        except Exception as e:
            logger.error(f"Failed to load experiment config: {e}")
    
    def assign_variant(self, user_id: str, experiment_id: str) -> str:
        """
        Assign user to experiment variant using sticky bucketing.
        Returns: variant name (control, variant_a, etc.)
        """
        if experiment_id not in self.experiments:
            return "control"  # Default if experiment not configured
        
        experiment = self.experiments[experiment_id]
        variants = experiment.get("variants", ["control"])
        
        # Use hash for consistent assignment
        hash_input = f"{user_id}:{experiment_id}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        
        # Get traffic split (default: equal split)
        traffic_split = experiment.get("traffic_split", {})
        total_weight = sum(traffic_split.values()) or len(variants)
        
        # Determine variant based on hash modulo
        bucket = hash_value % total_weight
        cumulative = 0
        
        for variant in variants:
            weight = traffic_split.get(variant, 1)
            cumulative += weight
            if bucket < cumulative:
                return variant
        
        return variants[-1]  # Fallback to last variant
    
    def log_event(self, experiment_id: str, user_id: str, variant: str,
                 query: str, success: bool, latency_ms: float,
                 confidence_score: float, reflexion_count: int):
        """Log an experiment event for later analysis."""
        event = ExperimentEvent(
            experiment_id=experiment_id,
            user_id=user_id,
            variant=variant,
            query=query,
            success=success,
            latency_ms=latency_ms,
            confidence_score=confidence_score,
            reflexion_count=reflexion_count,
            timestamp=datetime.now().isoformat()
        )
        
        self._append_to_jsonl({
            "experiment_id": event.experiment_id,
            "user_id": event.user_id,
            "variant": event.variant,
            "query": event.query,
            "success": event.success,
            "latency_ms": event.latency_ms,
            "confidence_score": event.confidence_score,
            "reflexion_count": event.reflexion_count,
            "timestamp": event.timestamp
        }, EXPERIMENT_LOG_PATH)
    
    def _append_to_jsonl(self, data: Dict[str, Any], filepath: str):
        """Append data to JSONL file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')
    
    def analyze_experiment(self, experiment_id: str) -> Dict[str, Any]:
        """
        Analyze experiment results and calculate statistical significance.
        Returns analysis report with winner declaration.
        """
        events = self._load_events_for_experiment(experiment_id)
        
        if not events:
            return {"error": "No events found for experiment"}
        
        # Group by variant
        variants: Dict[str, List[Dict]] = {}
        for event in events:
            variant = event["variant"]
            if variant not in variants:
                variants[variant] = []
            variants[variant].append(event)
        
        # Calculate metrics per variant
        results = {}
        for variant, variant_events in variants.items():
            n = len(variant_events)
            successes = sum(1 for e in variant_events if e["success"])
            avg_latency = sum(e["latency_ms"] for e in variant_events) / n if n > 0 else 0
            avg_confidence = sum(e["confidence_score"] for e in variant_events) / n if n > 0 else 0
            avg_reflexion = sum(e["reflexion_count"] for e in variant_events) / n if n > 0 else 0
            
            results[variant] = {
                "sample_size": n,
                "success_rate": successes / n if n > 0 else 0,
                "avg_latency_ms": round(avg_latency, 2),
                "avg_confidence": round(avg_confidence, 3),
                "avg_reflexion_count": round(avg_reflexion, 2)
            }
        
        # Statistical significance test (simplified chi-square for success rates)
        if len(results) >= 2:
            variant_names = list(results.keys())
            control = results[variant_names[0]]
            
            for variant_name in variant_names[1:]:
                variant = results[variant_name]
                
                # Simple z-test for proportions
                p1 = control["success_rate"]
                p2 = variant["success_rate"]
                n1 = control["sample_size"]
                n2 = variant["sample_size"]
                
                if n1 > 0 and n2 > 0:
                    p_pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
                    se = (p_pooled * (1 - p_pooled) * (1/n1 + 1/n2)) ** 0.5 if p_pooled not in [0, 1] else 0
                    
                    if se > 0:
                        z_score = (p2 - p1) / se
                        # Approximate p-value (two-tailed)
                        p_value = 2 * (1 - min(0.9999, abs(z_score) / 3.5))  # Simplified approximation
                        
                        results[variant_name]["vs_control"] = {
                            "success_rate_diff": round(p2 - p1, 4),
                            "z_score": round(z_score, 4),
                            "p_value": round(p_value, 4),
                            "significant": p_value < 0.05
                        }
        
        # Declare winner
        winner = None
        max_success_rate = 0
        
        for variant_name, metrics in results.items():
            if metrics["success_rate"] > max_success_rate:
                max_success_rate = metrics["success_rate"]
                winner = variant_name
        
        return {
            "experiment_id": experiment_id,
            "total_events": len(events),
            "variants": results,
            "winner": winner,
            "winner_success_rate": max_success_rate,
            "analyzed_at": datetime.now().isoformat()
        }
    
    def _load_events_for_experiment(self, experiment_id: str) -> List[Dict[str, Any]]:
        """Load all events for a specific experiment."""
        events = []
        
        if not os.path.exists(EXPERIMENT_LOG_PATH):
            return events
        
        try:
            with open(EXPERIMENT_LOG_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        event = json.loads(line)
                        if event.get("experiment_id") == experiment_id:
                            events.append(event)
        except Exception as e:
            logger.error(f"Failed to load experiment events: {e}")
        
        return events
    
    def get_active_experiments(self) -> List[str]:
        """Get list of active experiment IDs."""
        return [
            exp_id for exp_id, config in self.experiments.items()
            if config.get("active", True)
        ]
