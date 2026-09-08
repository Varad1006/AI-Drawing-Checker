import re

class EntityExtractor:
    def __init__(self, raw_entities):
        self.raw_entities = raw_entities
        self.engineering_entities = []

    def extract(self):
        # Very simple heuristic for POC
        # If we see a text like P-101, it's a pump
        
        tag_patterns = {
            r'^P-\d+': 'pump',
            r'^TK-\d+': 'tank',
            r'^V-\d+': 'valve',
            r'^XV-\d+': 'actuated_valve',
            r'^FT-\d+': 'flow_transmitter',
            r'^PT-\d+': 'pressure_transmitter',
            r'^LT-\d+': 'level_transmitter',
            r'^L-\d+': 'pipe_line'
        }
        
        counter = 1
        for e in self.raw_entities:
            if e['entity_type'] == 'text':
                content = e.get('content', '')
                for pattern, etype in tag_patterns.items():
                    if re.match(pattern, content):
                        self.engineering_entities.append({
                            "entity_id": f"ent_{counter}",
                            "type": etype,
                            "tag": content,
                            "pos_x": e['position'][0],
                            "pos_y": e['position'][1],
                            "source_entities": [e]
                        })
                        counter += 1
                        break
                        
        return self.engineering_entities
