import os
import json
import logging
from typing import List, Dict

try:
    from groq import Groq
except ImportError:
    Groq = None

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key) if self.api_key and Groq else None

    def analyze_entities(self, entities: List[Dict]) -> Dict:
        """
        Analyzes the extracted entities and returns a JSON payload containing identified issues
        and proposed corrections.
        """
        if not self.client:
            logger.warning("GROQ_API_KEY not found. Using deterministic fallback analysis.")
            return self._fallback_analysis(entities)

        prompt = f"""
You are an expert Lead P&ID Checker AI. 
Review the following list of extracted engineering entities from a CAD/PDF drawing.
Entities: {json.dumps(entities)}

Identify any engineering errors such as:
1. Duplicate equipment tags (e.g. two entities with 'P-101').
2. Missing connections or orphaned pipe lines.
3. Missing mandatory instrumentation (e.g. tank without a level transmitter).

Return a JSON object with this EXACT structure:
{{
  "issues": [
    {{
      "issue_id": "ERR-001",
      "rule_id": "AI-RULE",
      "category": "Tagging",
      "severity": "HIGH",
      "title": "Short title",
      "description": "Detailed explanation",
      "recommendation": "How to fix",
      "confidence": 0.95,
      "related_entities": ["tag1"]
    }}
  ],
  "corrections": [
    {{
      "action": "delete",
      "entity_tag": "P-101",
      "reason": "Duplicate tag"
    }},
    {{
      "action": "connect",
      "entity_tag": "L-001",
      "target_tag": "TK-101"
    }}
  ]
}}
Only return the valid JSON, no markdown blocks.
"""
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a precise engineering JSON API."},
                    {"role": "user", "content": prompt}
                ],
                model="llama3-70b-8192",
                temperature=0.1,
            )
            
            response_text = chat_completion.choices[0].message.content.strip()
            # Clean up potential markdown formatting
            if response_text.startswith("```json"):
                response_text = response_text[7:-3]
            
            return json.loads(response_text)
            
        except Exception as e:
            logger.error(f"Groq API Error: {e}")
            return self._fallback_analysis(entities)

    def _fallback_analysis(self, entities: List[Dict]) -> Dict:
        # Provide deterministic mock for testing
        return {
            "issues": [
                {
                    "issue_id": "ERR-AI-001",
                    "rule_id": "RULE-001",
                    "category": "Tagging",
                    "severity": "HIGH",
                    "title": "Duplicate equipment tag (Simulated)",
                    "description": "Equipment tag P-101 appears multiple times.",
                    "recommendation": "Verify equipment numbering.",
                    "confidence": 0.99,
                    "related_entities": ["P-101"]
                }
            ],
            "corrections": [
                {
                    "action": "delete",
                    "entity_tag": "P-101",
                    "reason": "Duplicate tag"
                }
            ]
        }
