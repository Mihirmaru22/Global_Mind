"""
Multi-Turn Query Refinement - Context Gatekeeper
Determines if a query is a follow-up (REFINE), new topic (RESET), or ambiguous (ASK).
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ContextAction(Enum):
    RESET = "reset"  # New topic, ignore previous context
    REFINE = "refine"  # Follow-up, merge with previous context
    ASK = "ask"  # Ambiguous, need clarification


@dataclass
class ConversationState:
    previous_query: str
    previous_sql: str
    previous_filters: Dict[str, Any]
    previous_tables: List[str]
    timestamp: str


class ContextGatekeeper:
    """Classifies queries and manages context inheritance for multi-turn conversations."""
    
    def __init__(self):
        self.conversation_history: List[ConversationState] = []
        self.max_history = 5  # Keep last 5 turns
        
        # Linguistic markers for follow-ups
        self.followup_markers = [
            "what about", "how about", "and", "also", "then",
            "show me", "list", "give me", "break down",
            "by", "per", "each", "respectively",
            "same", "previous", "last", "earlier"
        ]
        
        # Reset markers (new topic)
        self.reset_markers = [
            "new question", "different", "change topic",
            "let's talk about", "switch to", "start over",
            "ignore previous", "forget about"
        ]
    
    def classify_query(self, current_query: str, 
                      has_explicit_filters: bool = False) -> Tuple[ContextAction, Optional[str]]:
        """
        Classify if query needs context reset, refinement, or clarification.
        Returns: (action, clarification_message if ASK)
        """
        query_lower = current_query.lower()
        
        # Check for explicit reset markers
        if any(marker in query_lower for marker in self.reset_markers):
            logger.info("Reset marker detected - starting fresh context")
            return ContextAction.RESET, None
        
        # Check if query has complete explicit filters (overrides context)
        if has_explicit_filters:
            # Has specific time range, entities, etc. - likely RESET
            if self._has_complete_specification(current_query):
                logger.info("Complete specification detected - resetting context")
                return ContextAction.RESET, None
        
        # Check for follow-up markers
        if any(marker in query_lower for marker in self.followup_markers):
            if not self.conversation_history:
                # No history to refine from
                logger.warning("Follow-up detected but no conversation history")
                return ContextAction.ASK, "I don't have context from previous questions. Could you please rephrase with more details?"
            
            logger.info("Follow-up detected - refining with previous context")
            return ContextAction.REFINE, None
        
        # Check for pronouns/ambiguous references
        if self._has_ambiguous_references(current_query):
            if not self.conversation_history:
                return ContextAction.ASK, "Could you clarify what you're referring to?"
            
            # Try to resolve from context
            resolved = self._resolve_references(current_query)
            if not resolved:
                return ContextAction.ASK, f"Are you asking about {self._get_last_topic()}?"
            
            return ContextAction.REFINE, None
        
        # Default: if we have history and query is short, likely follow-up
        if self.conversation_history and len(current_query.split()) < 10:
            return ContextAction.REFINE, None
        
        # Otherwise, treat as new topic
        return ContextAction.RESET, None
    
    def _has_complete_specification(self, query: str) -> bool:
        """Check if query has complete time/entity specifications."""
        import re
        
        # Check for explicit date ranges
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'last\s+\w+',  # last month/year
            r'next\s+\w+',  # next week
            r'from\s+.*\s+to\s+',  # from X to Y
            r'between\s+.*\s+and\s+'  # between X and Y
        ]
        
        has_date = any(re.search(p, query.lower()) for p in date_patterns)
        
        # Check for explicit entities
        entity_patterns = [
            r'all\s+\w+s?',  # all products/customers
            r'each\s+\w+',  # each product
            r'every\s+\w+'  # every customer
        ]
        
        has_entity = any(re.search(p, query.lower()) for p in entity_patterns)
        
        return has_date or has_entity
    
    def _has_ambiguous_references(self, query: str) -> bool:
        """Check for pronouns and ambiguous references."""
        ambiguous_words = [
            "it", "they", "them", "their", "its",
            "this", "that", "these", "those",
            "which", "who", "whom", "whose"
        ]
        
        query_lower = query.lower()
        return any(word in query_lower for word in ambiguous_words)
    
    def _resolve_references(self, query: str) -> bool:
        """Attempt to resolve ambiguous references from context."""
        if not self.conversation_history:
            return False
        
        last_state = self.conversation_history[-1]
        
        # Simple resolution - check if pronouns can map to previous entities
        if "they" in query.lower() or "them" in query.lower():
            # Likely refers to previous subject
            return True
        
        if "it" in query.lower():
            # Likely refers to previous object
            return True
        
        return False
    
    def _get_last_topic(self) -> str:
        """Get the main topic from last query."""
        if not self.conversation_history:
            return "your previous question"
        
        # Extract key nouns from last query (simplified)
        last_query = self.conversation_history[-1].previous_query
        words = last_query.split()
        
        # Return first significant noun phrase
        for word in words:
            if word.lower() not in ['the', 'a', 'an', 'is', 'are', 'was', 'were', 'show', 'give', 'list']:
                return word
        
        return "your previous question"
    
    def merge_contexts(self, current_query: str, 
                      current_filters: Dict[str, Any]) -> Dict[str, Any]:
        """Merge previous context filters with current query filters."""
        if not self.conversation_history:
            return current_filters
        
        last_state = self.conversation_history[-1]
        merged = last_state.previous_filters.copy()
        
        # Override with current filters (explicit takes precedence)
        merged.update(current_filters)
        
        logger.info(f"Merged context: {len(last_state.previous_filters)} previous + {len(current_filters)} current = {len(merged)} total")
        return merged
    
    def update_history(self, query: str, sql: str, filters: Dict[str, Any], tables: List[str]):
        """Add current turn to conversation history."""
        from datetime import datetime
        
        state = ConversationState(
            previous_query=query,
            previous_sql=sql,
            previous_filters=filters,
            previous_tables=tables,
            timestamp=datetime.now().isoformat()
        )
        
        self.conversation_history.append(state)
        
        # Trim history if too long
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)
        
        logger.debug(f"Updated conversation history: {len(self.conversation_history)} turns")
    
    def clear_history(self):
        """Clear conversation history (user requested reset)."""
        self.conversation_history.clear()
        logger.info("Cleared conversation history")
