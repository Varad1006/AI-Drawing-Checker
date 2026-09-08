import os
from dotenv import load_dotenv

load_dotenv()

import json
import logging
from typing import List, Dict

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key and genai else None

    def analyze_entities(self, entities: List[Dict]) -> Dict:
        """
        Analyzes the extracted entities and returns a JSON payload containing identified issues
        and proposed corrections.
        """
        if not self.client:
            logger.warning("GEMINI_API_KEY not found. Using deterministic fallback analysis.")
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
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            
            return json.loads(response.text)
            
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
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
