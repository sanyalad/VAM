from PyQt6.QtCore import QThread, pyqtSignal
from ai_parser import ingest_document

class IngestWorker(QThread):
    finished = pyqtSignal(bool, str)
    
    def __init__(self, filepath, user_comment=""):
        super().__init__()
        self.filepath = filepath
        self.user_comment = user_comment
        
    def run(self):
        success, msg = ingest_document(self.filepath, self.user_comment)
        self.finished.emit(success, msg)
