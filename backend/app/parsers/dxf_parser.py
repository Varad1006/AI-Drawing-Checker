import ezdxf
import logging

logger = logging.getLogger(__name__)

class DXFParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.doc = None

    def parse(self):
        try:
            self.doc = ezdxf.readfile(self.file_path)
            msp = self.doc.modelspace()
            
            entities = []
            
            # Extract texts
            for text in msp.query('TEXT MTEXT'):
                entities.append({
                    "entity_type": "text",
                    "content": text.dxf.text if hasattr(text.dxf, 'text') else getattr(text, 'text', ''),
                    "position": [text.dxf.insert.x, text.dxf.insert.y] if hasattr(text.dxf, 'insert') else [0,0],
                    "layer": text.dxf.layer
                })
                
            # Extract inserts (blocks)
            for insert in msp.query('INSERT'):
                entities.append({
                    "entity_type": "block",
                    "block_name": insert.dxf.name,
                    "position": [insert.dxf.insert.x, insert.dxf.insert.y],
                    "rotation": insert.dxf.rotation if hasattr(insert.dxf, 'rotation') else 0,
                    "layer": insert.dxf.layer
                })

            # Extract lines
            for line in msp.query('LINE'):
                entities.append({
                    "entity_type": "line",
                    "start": [line.dxf.start.x, line.dxf.start.y],
                    "end": [line.dxf.end.x, line.dxf.end.y],
                    "layer": line.dxf.layer
                })
                
            return entities
        except Exception as e:
            logger.error(f"Error parsing DXF: {e}")
            return []
