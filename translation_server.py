import http.server
import urllib.parse
import threading
import sys
import os

sys.path.insert(0, r'D:\GameArabicTranslator')
os.chdir(r'D:\GameArabicTranslator')

import arabic_reshaper
from bidi.algorithm import get_display
from engine.translator import TranslationEngine
from engine.cache import TranslationCache

GAME_NAME = "Manor Lords"
engine = TranslationEngine()
cache = TranslationCache(r'D:\GameArabicTranslator\data\cache\translations.db')
engine.set_active_model("google_free")
engine.load_model("google_free")

print("Translation engine ready")

def translate_text(text):
    cached = cache.get(GAME_NAME, text)
    if cached:
        return cached
    
    result = engine.translate(text)
    if result:
        cache.put(GAME_NAME, text, result, "google_free")
        return result
    return text

def apply_rtl_visual(text):
    try:
        parts = text.split("\\n")
        fixed = [arabic_reshaper.reshape(p) for p in parts]
        result = "\\n".join(fixed)
        return '<align="right">' + result
    except:
        return text

class TranslationHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        text = params.get("text", [""])[0].strip()
        
        if parsed.path == "/health":
            self._respond(200, b'{"status":"running"}', "application/json")
            return
        
        if not text:
            self._respond(200, b"", "text/plain")
            return
        
        try:
            arabic = translate_text(text)
            if not arabic:
                arabic = text
            
            arabic = apply_rtl_visual(arabic)
            
            print(f"  {text[:40]:40s} => {arabic[:40]}")
            
            self._respond(200, arabic.encode("utf-8"), "text/plain; charset=utf-8")
        except Exception as e:
            print(f"Error: {e}")
            self._respond(200, text.encode("utf-8"), "text/plain; charset=utf-8")
    
    def _respond(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def log_message(self, *args):
        pass

server = http.server.HTTPServer(("127.0.0.1", 5001), TranslationHandler)
print("Server running on http://127.0.0.1:5001")
print("Waiting for game connections...")
server.serve_forever()
