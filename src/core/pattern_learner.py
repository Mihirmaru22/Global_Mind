"""
Dynamic Pattern Learning Engine
Captures successful reflexion fixes, abstracts them into patterns, and merges with static library.
"""
import json
import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

LEARNED_PATTERNS_PATH = "data/learned_patterns.jsonl"
LEARNING_METRICS_PATH = "data/learning_metrics.json"


@dataclass
class LearnedPattern:
    pattern_id: str
    business_scenario: str
    trigger_phrases: List[str]
    cot_reasoning_snippet: str
    sql_structure_template: str
    source_question: str
    original_error: str
    fixed_sql: str
    created_at: str
    success_count: int = 1
    last_used: str = None
    quality_score: float = 0.8


class PatternLearner:
    """Manages dynamic learning of SQL patterns from successful reflexion fixes."""
    
    def __init__(self, static_patterns_path: str = "config/sql_pattern_library.json"):
        self.static_patterns_path = static_patterns_path
        self.learned_patterns: List[LearnedPattern] = []
        self.metrics = {
            "total_learned": 0,
            "total_promoted": 0,
            "success_rate": 0.0,
            "last_updated": None
        }
        self._load_learned_patterns()
        self._load_metrics()
    
    def _load_learned_patterns(self):
        """Load learned patterns from JSONL file."""
        if not os.path.exists(LEARNED_PATTERNS_PATH):
            return
        
        try:
            with open(LEARNED_PATTERNS_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self.learned_patterns.append(LearnedPattern(**data))
            logger.info(f"Loaded {len(self.learned_patterns)} learned patterns")
        except Exception as e:
            logger.error(f"Failed to load learned patterns: {e}")
    
    def _load_metrics(self):
        """Load learning metrics from JSON file."""
        if not os.path.exists(LEARNING_METRICS_PATH):
            return
        
        try:
            with open(LEARNING_METRICS_PATH, 'r', encoding='utf-8') as f:
                self.metrics = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load learning metrics: {e}")
    
    def capture_success(self, user_question: str, original_cot: str, 
                       failed_sql: str, error_message: str, 
                       fixed_sql: str, revised_cot: str) -> Optional[LearnedPattern]:
        """Capture a successful reflexion fix as a learnable pattern."""
        
        # Extract the generalizable pattern from the specific fix
        pattern = self._abstract_pattern(
            user_question=user_question,
            original_cot=original_cot,
            failed_sql=failed_sql,
            error_message=error_message,
            fixed_sql=fixed_sql,
            revised_cot=revised_cot
        )
        
        if not pattern:
            return None
        
        # Save the pattern
        self.learned_patterns.append(pattern)
        self._append_to_jsonl(asdict(pattern), LEARNED_PATTERNS_PATH)
        
        # Update metrics
        self.metrics["total_learned"] += 1
        self.metrics["last_updated"] = datetime.now().isoformat()
        self._save_metrics()
        
        logger.info(f"Captured new pattern: {pattern.pattern_id}")
        return pattern
    
    def _abstract_pattern(self, user_question: str, original_cot: str,
                         failed_sql: str, error_message: str,
                         fixed_sql: str, revised_cot: str) -> Optional[LearnedPattern]:
        """Abstract a specific fix into a generalizable pattern."""
        
        # Identify the key fix applied
        fix_type = self._identify_fix_type(failed_sql, fixed_sql, error_message)
        if not fix_type:
            return None
        
        # Generate trigger phrases from the question
        trigger_phrases = self._extract_trigger_phrases(user_question)
        
        # Create the pattern
        pattern_id = f"learned_{fix_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return LearnedPattern(
            pattern_id=pattern_id,
            business_scenario=f"Auto-learned from: {user_question[:100]}",
            trigger_phrases=trigger_phrases,
            cot_reasoning_snippet=self._extract_reasoning(revised_cot, fix_type),
            sql_structure_template=self._generalize_sql(fixed_sql),
            source_question=user_question,
            original_error=error_message,
            fixed_sql=fixed_sql,
            created_at=datetime.now().isoformat(),
            quality_score=0.8
        )
    
    def _identify_fix_type(self, failed_sql: str, fixed_sql: str, 
                          error_message: str) -> Optional[str]:
        """Identify what type of fix was applied."""
        error_lower = error_message.lower()
        
        if "cast" in error_lower or "varchar" in error_lower or "numeric" in error_lower:
            return "varchar_cast"
        elif "deleted_at" in error_lower or "soft delete" in error_lower:
            return "soft_delete"
        elif "join" in error_lower or "on clause" in error_lower:
            return "join_correction"
        elif "group by" in error_lower:
            return "group_by_fix"
        elif "cross join" in error_lower or "cartesian" in error_lower:
            return "cross_join_prevention"
        
        # Compare SQL strings to detect changes
        if "CAST(" in fixed_sql and "CAST(" not in failed_sql:
            return "varchar_cast"
        elif "LEFT JOIN" in fixed_sql and "INNER JOIN" in failed_sql:
            return "sparse_table_left_join"
        elif "deleted_at IS NULL" in fixed_sql and "deleted_at" not in failed_sql:
            return "soft_delete"
        
        return None
    
    def _extract_trigger_phrases(self, question: str) -> List[str]:
        """Extract potential trigger phrases from the user question."""
        import re
        
        # Extract key phrases (2-4 word sequences)
        words = question.lower().split()
        phrases = []
        
        for length in [2, 3, 4]:
            for i in range(len(words) - length + 1):
                phrase = " ".join(words[i:i+length])
                # Filter out common stop words
                if not any(word in phrase for word in ["the", "a", "an", "is", "are", "was", "were"]):
                    phrases.append(phrase)
        
        return phrases[:10]  # Limit to top 10
    
    def _extract_reasoning(self, revised_cot: str, fix_type: str) -> str:
        """Extract the reasoning snippet from revised CoT."""
        # Simple extraction - look for key reasoning markers
        markers = ["because", "therefore", "must", "should", "need to"]
        sentences = revised_cot.split('.')
        
        for sentence in sentences:
            if any(marker in sentence.lower() for marker in markers):
                return sentence.strip() + "."
        
        return f"Applied {fix_type} correction based on previous failure."
    
    def _generalize_sql(self, fixed_sql: str) -> str:
        """Generalize specific SQL into a template."""
        import re
        
        template = fixed_sql
        
        # Replace specific table names with placeholders
        template = re.sub(r'\b(product|party|sales_order|purchase)\b', '{table}', template, flags=re.IGNORECASE)
        
        # Replace specific column names with placeholders  
        template = re.sub(r'\b(qty|quantity|amount|price|total)\b', '{column}', template, flags=re.IGNORECASE)
        
        return template
    
    def _append_to_jsonl(self, data: Dict[str, Any], filepath: str):
        """Append data to JSONL file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')
    
    def _save_metrics(self):
        """Save learning metrics to JSON file."""
        os.makedirs(os.path.dirname(LEARNING_METRICS_PATH), exist_ok=True)
        with open(LEARNING_METRICS_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.metrics, f, indent=2)
    
    def get_patterns_for_query(self, user_question: str, top_k: int = 2) -> List[LearnedPattern]:
        """Retrieve relevant learned patterns for a query."""
        scored = []
        question_lower = user_question.lower()
        
        for pattern in self.learned_patterns:
            score = 0
            for phrase in pattern.trigger_phrases:
                if phrase in question_lower:
                    score += 2
            
            # Boost recent, high-quality patterns
            score *= pattern.quality_score
            
            if score > 0:
                scored.append((score, pattern))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]
    
    def promote_pattern(self, pattern_id: str) -> bool:
        """Promote a learned pattern to static library (manual review step)."""
        for pattern in self.learned_patterns:
            if pattern.pattern_id == pattern_id:
                pattern.quality_score = 1.0
                self.metrics["total_promoted"] += 1
                self._save_metrics()
                
                # Append to static library
                self._append_to_static_library(pattern)
                logger.info(f"Promoted pattern {pattern_id} to static library")
                return True
        
        return False
    
    def _append_to_static_library(self, pattern: LearnedPattern):
        """Append a learned pattern to the static pattern library."""
        if not os.path.exists(self.static_patterns_path):
            return
        
        try:
            with open(self.static_patterns_path, 'r', encoding='utf-8') as f:
                library = json.load(f)
            
            library.append({
                "pattern_id": pattern.pattern_id.replace("learned_", ""),
                "business_scenario": pattern.business_scenario,
                "trigger_phrases": pattern.trigger_phrases,
                "cot_reasoning_snippet": pattern.cot_reasoning_snippet,
                "sql_structure_template": pattern.sql_structure_template
            })
            
            with open(self.static_patterns_path, 'w', encoding='utf-8') as f:
                json.dump(library, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to append to static library: {e}")
    
    def apply_decay(self):
        """Apply decay to unused patterns over time."""
        from datetime import timedelta
        
        now = datetime.now()
        for pattern in self.learned_patterns:
            if pattern.last_used:
                last_used = datetime.fromisoformat(pattern.last_used)
                days_unused = (now - last_used).days
                
                # Decay quality score by 0.01 per day unused
                if days_unused > 7:
                    pattern.quality_score = max(0.1, pattern.quality_score - (days_unused * 0.01))
