"""
Explainable Confidence Scoring Engine
Calculates dynamic confidence scores based on pattern matches, validation results, 
execution efficiency, and query complexity.
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceBreakdown:
    pattern_score: float
    validation_score: float
    execution_score: float
    complexity_score: float
    final_score: float
    explanations: List[str]


class ConfidenceScorer:
    """Calculates and explains confidence scores for SQL query results."""
    
    # Weights for each factor
    WEIGHTS = {
        "pattern": 0.30,      # Pattern match strength
        "validation": 0.40,   # Validation health
        "execution": 0.20,    # Execution efficiency (retries)
        "complexity": 0.10    # Query complexity risk
    }
    
    def __init__(self):
        pass
    
    def calculate(self, 
                 pattern_matches: int = 0,
                 total_patterns: int = 5,
                 validation_results: Optional[List[Any]] = None,
                 reflexion_attempts: int = 0,
                 max_reflexion: int = 3,
                 query_complexity: Optional[Dict[str, Any]] = None) -> ConfidenceBreakdown:
        """
        Calculate overall confidence score with detailed breakdown.
        
        Args:
            pattern_matches: Number of matched patterns (static + learned)
            total_patterns: Total available patterns
            validation_results: List of ValidationResult objects
            reflexion_attempts: Number of reflexion retries needed
            max_reflexion: Maximum allowed reflexion attempts
            query_complexity: Dict with keys: join_count, subquery_depth, has_cross_join
        
        Returns:
            ConfidenceBreakdown with scores and explanations
        """
        explanations = []
        
        # 1. Pattern Strength Score (0-1)
        if pattern_matches > 0 and total_patterns > 0:
            pattern_score = min(1.0, 0.85 + (pattern_matches / total_patterns) * 0.15)
            explanations.append(f"High confidence: Matched {pattern_matches} relevant pattern(s)")
        else:
            pattern_score = 0.85
            explanations.append("First-principles reasoning - no prior pattern required")
        
        # 2. Validation Health Score (0-1)
        validation_score = 1.0
        if validation_results:
            critical_failures = sum(1 for r in validation_results if not r.passed and r.severity.value == "critical")
            warning_failures = sum(1 for r in validation_results if not r.passed and r.severity.value == "warning")
            
            validation_score -= critical_failures * 0.3
            validation_score -= warning_failures * 0.1
            validation_score = max(0.0, min(1.0, validation_score))
            
            if critical_failures > 0:
                explanations.append(f"Critical: {critical_failures} validation failure(s) detected")
            if warning_failures > 0:
                explanations.append(f"Warning: {warning_failures} potential issue(s) found")
        
        if validation_score == 1.0:
            explanations.append("All validation checks passed")
        
        # 3. Execution Efficiency Score (0-1)
        if reflexion_attempts == 0:
            execution_score = 1.0
            explanations.append("First-try success - no corrections needed")
        else:
            execution_score = max(0.1, 1.0 - (reflexion_attempts / max_reflexion))
            explanations.append(f"Required {reflexion_attempts} correction attempt(s)")
        
        # 4. Complexity Risk Score (0-1)
        complexity_score = 1.0
        if query_complexity:
            # Penalize high complexity
            join_count = query_complexity.get("join_count", 0)
            subquery_depth = query_complexity.get("subquery_depth", 0)
            has_cross_join = query_complexity.get("has_cross_join", False)
            
            if join_count > 5:
                complexity_score -= 0.1
                explanations.append("High join count may increase error risk")
            
            if subquery_depth > 2:
                complexity_score -= 0.15
                explanations.append("Deep subqueries increase complexity risk")
            
            if has_cross_join:
                complexity_score -= 0.3
                explanations.append("Cross join detected - verify intent")
            
            complexity_score = max(0.0, min(1.0, complexity_score))
        
        # Calculate weighted final score
        final_score = (
            pattern_score * self.WEIGHTS["pattern"] +
            validation_score * self.WEIGHTS["validation"] +
            execution_score * self.WEIGHTS["execution"] +
            complexity_score * self.WEIGHTS["complexity"]
        )
        
        final_score = round(max(0.0, min(1.0, final_score)), 2)
        
        # Add overall assessment
        if final_score >= 0.8:
            explanations.append("Overall: HIGH CONFIDENCE - Ready for production use")
        elif final_score >= 0.5:
            explanations.append("Overall: MEDIUM CONFIDENCE - Review recommended")
        else:
            explanations.append("Overall: LOW CONFIDENCE - Human review required")
        
        return ConfidenceBreakdown(
            pattern_score=round(pattern_score, 2),
            validation_score=round(validation_score, 2),
            execution_score=round(execution_score, 2),
            complexity_score=round(complexity_score, 2),
            final_score=final_score,
            explanations=explanations
        )
    
    def get_confidence_badge(self, score: float) -> str:
        """Get UI badge color based on confidence score."""
        if score >= 0.8:
            return "green"  # High confidence
        elif score >= 0.5:
            return "yellow"  # Medium confidence
        else:
            return "red"  # Low confidence
    
    def should_flag_for_review(self, score: float) -> bool:
        """Determine if result should be flagged for human review."""
        return score < 0.5
