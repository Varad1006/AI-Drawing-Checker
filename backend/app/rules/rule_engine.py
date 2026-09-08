from typing import List, Dict

class RuleEngine:
    def __init__(self, entities: List[Dict]):
        self.entities = entities
        self.issues = []

    def run_all(self):
        self.rule_duplicate_equipment()
        return self.issues

    def rule_duplicate_equipment(self):
        tags = {}
        for ent in self.entities:
            if 'tag' in ent and ent['tag']:
                t = ent['tag']
                if t in tags:
                    tags[t].append(ent)
                else:
                    tags[t] = [ent]
                    
        for tag, ents in tags.items():
            if len(ents) > 1:
                # Issue detected
                for ent in ents[1:]:
                    self.issues.append({
                        "issue_id": f"ERR-DUP-{tag}",
                        "rule_id": "RULE-001",
                        "category": "Tagging",
                        "severity": "HIGH",
                        "title": "Duplicate equipment tag",
                        "description": f"Equipment tag {tag} appears multiple times.",
                        "recommendation": "Verify equipment numbering and assign unique tags.",
                        "confidence": 0.99,
                        "pos_x": ent['pos_x'],
                        "pos_y": ent['pos_y'],
                        "related_entities": [tag]
                    })
