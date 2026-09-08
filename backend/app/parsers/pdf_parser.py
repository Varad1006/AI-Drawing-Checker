import fitz  # PyMuPDF
import logging
import re

logger = logging.getLogger(__name__)

class PDFParser:
    def __init__(self, file_path):
        self.file_path = file_path
        
    def parse(self):
        entities = []
        try:
            doc = fitz.open(self.file_path)
            # For POC, parse just the first page
            page = doc[0]
            
            # Extract Text Blocks
            blocks = page.get_text("dict")["blocks"]
            for b in blocks:
                if b['type'] == 0:  # text block
                    for l in b["lines"]:
                        for s in l["spans"]:
                            text = s["text"].strip()
                            if text:
                                # Scale coordinates (roughly to fit our -1000 to 1000 canvas)
                                # PyMuPDF origin is top-left, our canvas is center origin
                                x = (s["bbox"][0] - 300) * 2
                                y = -(s["bbox"][1] - 400) * 2
                                entities.append({
                                    "entity_type": "text",
                                    "content": text,
                                    "position": [x, y]
                                })
                                
            return entities
        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            return []
