import pytest
from app.extraction.entity_extractor import EntityExtractor
from app.rules.rule_engine import RuleEngine

def test_entity_extraction():
    raw = [
        {"entity_type": "text", "content": "P-101", "position": [0,0]},
        {"entity_type": "text", "content": "TK-101", "position": [10,10]},
        {"entity_type": "line", "start": [0,0], "end": [10,10]}
    ]
    extractor = EntityExtractor(raw)
    entities = extractor.extract()
    
    assert len(entities) == 2
    assert entities[0]['type'] == 'pump'
    assert entities[1]['type'] == 'tank'

def test_rule_duplicate():
    entities = [
        {"entity_id": "1", "tag": "P-101", "type": "pump", "pos_x": 0, "pos_y": 0},
        {"entity_id": "2", "tag": "P-101", "type": "pump", "pos_x": 10, "pos_y": 10},
        {"entity_id": "3", "tag": "V-101", "type": "valve", "pos_x": 20, "pos_y": 20}
    ]
    engine = RuleEngine(entities)
    issues = engine.run_all()
    
    assert len(issues) == 1
    assert issues[0]['rule_id'] == 'RULE-001'
    assert issues[0]['related_entities'][0] == 'P-101'
