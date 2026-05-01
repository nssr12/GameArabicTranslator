import os
import json
import threading
import time
from typing import Optional, Callable, Dict, List


class FridaManager:
    
    def __init__(self):
        self._frida = None
        self._device = None
        self._session = None
        self._script = None
        self._process = None
        self._is_attached = False
        self._on_text_callback: Optional[Callable] = None
        self._on_log_callback: Optional[Callable] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._pending_translations: Dict[int, dict] = {}
        self._request_counter = 0
    
    def _import_frida(self):
        if self._frida is None:
            try:
                import frida
                self._frida = frida
                return True
            except ImportError:
                print("[Frida] frida not installed. Run: pip install frida frida-tools")
                return False
        return True
    
    def _get_device(self):
        if self._device is None:
            try:
                self._device = self._frida.get_local_device()
            except Exception:
                self._device = self._frida.get_device_manager().get_local_device()
        return self._device
    
    def set_callbacks(self, on_text: Callable = None, on_log: Callable = None):
        self._on_text_callback = on_text
        self._on_log_callback = on_log
    
    def attach_to_process(self, process_name_or_pid) -> bool:
        if not self._import_frida():
            return False
        
        try:
            device = self._get_device()
            
            if isinstance(process_name_or_pid, int):
                self._session = device.attach(process_name_or_pid)
                print(f"[Frida] Attached to PID: {process_name_or_pid}")
            else:
                self._session = device.attach(process_name_or_pid)
                print(f"[Frida] Attached to process: {process_name_or_pid}")
            
            self._is_attached = True
            return True
        except Exception as e:
            print(f"[Frida] Failed to attach: {e}")
            return False
    
    def load_script(self, script_content: str) -> bool:
        if not self._is_attached or not self._session:
            print("[Frida] Not attached to any process")
            return False
        
        try:
            self._script = self._session.create_script(script_content)
            self._script.on('message', self._on_message)
            self._script.load()
            print("[Frida] Script loaded successfully")
            return True
        except Exception as e:
            print(f"[Frida] Failed to load script: {e}")
            return False
    
    def load_script_file(self, script_path: str) -> bool:
        if not os.path.exists(script_path):
            print(f"[Frida] Script not found: {script_path}")
            return False
        
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        return self.load_script(content)
    
    def load_game_hooks(self, game_config: dict, hooks_dir: str = "hooking/hooks") -> bool:
        hooks = game_config.get("hooks", [])
        if not hooks:
            hook_type = game_config.get("hook_mode", "frida")
            script_path = os.path.join(hooks_dir, "generic_hook.js")
            if os.path.exists(script_path):
                return self.load_script_file(script_path)
            else:
                print("[Frida] No hooks configured and no generic hook found")
                return False
        
        script_content = hooks[0].get("script", "")
        if script_content:
            return self.load_script(script_content)
        
        script_file = hooks[0].get("file", "")
        if script_file:
            full_path = os.path.join(hooks_dir, script_file)
            return self.load_script_file(full_path)
        
        return False
    
    def _on_message(self, message, data):
        if message.get('type') == 'send':
            payload = message.get('payload', {})
            msg_type = payload.get('type', '')
            
            if msg_type == 'text_intercepted':
                self._handle_text_intercepted(payload)
            elif msg_type == 'translate-sync-with-confirmation':
                self._handle_sync_translation(payload)
            elif msg_type == 'translate-async':
                self._handle_async_translation(payload)
            elif msg_type == 'text_found':
                self._handle_text_found(payload)
            elif msg_type == 'load-json-translations':
                self._handle_load_json_translations()
            elif msg_type == 'load-cache':
                self._handle_load_cache()
            elif msg_type == 'log':
                if self._on_log_callback:
                    self._on_log_callback(payload.get('message', ''))
            else:
                if self._on_log_callback:
                    self._on_log_callback(f"[Frida] {payload}")
        
        elif message.get('type') == 'error':
            print(f"[Frida] Error: {message.get('description', '')}")
    
    def _handle_text_intercepted(self, payload):
        text_id = payload.get('id', 0)
        text = payload.get('text', '')
        encoding = payload.get('encoding_hint', 'CString')
        
        if text and self._on_text_callback:
            result = self._on_text_callback(text, 'intercepted')
            if result and result != text:
                self.send_translation_to_game(text_id, text, result, encoding)
    
    def _handle_sync_translation(self, payload):
        request_id = payload.get('requestId', 0)
        text = payload.get('text', '')
        
        translated = None
        if self._on_text_callback:
            translated = self._on_text_callback(text, 'sync')
        
        self.send_translation_confirmation(request_id, text, translated or text)
    
    def _handle_async_translation(self, payload):
        text = payload.get('text', '')
        
        if text and self._on_text_callback:
            result = self._on_text_callback(text, 'async')
            if result and result != text:
                self.send_async_translation(text, result)
    
    def _handle_text_found(self, payload):
        text = payload.get('text', '')
        address = payload.get('address', '')
        
        if text and self._on_text_callback:
            result = self._on_text_callback(text, 'found')
            if result and result != text:
                self.send_translation_to_memory(address, result)
    
    def _handle_load_json_translations(self):
        if self._on_log_callback:
            self._on_log_callback("[Frida] Game requested JSON translations")
    
    def _handle_load_cache(self):
        if self._on_log_callback:
            self._on_log_callback("[Frida] Game requested cache")
    
    def send_translation_to_game(self, text_id: int, original: str, translated: str, encoding: str = "CString"):
        if not self._script:
            return
        
        try:
            self._script.exports_sync.processmodificationcommand({
                "id": text_id,
                "new_text": translated,
                "encoding": encoding
            })
        except Exception as e:
            print(f"[Frida] Send modification failed: {e}")
    
    def send_translation_confirmation(self, request_id: int, original: str, translated: str):
        if not self._script:
            return
        
        try:
            self._script.post({
                "type": "translation-confirmation",
                "requestId": request_id,
                "original": original,
                "translated": translated
            })
        except Exception as e:
            print(f"[Frida] Send confirmation failed: {e}")
    
    def send_async_translation(self, original: str, translated: str):
        if not self._script:
            return
        
        try:
            self._script.post({
                "type": "translation",
                "original": original,
                "translated": translated
            })
        except Exception as e:
            print(f"[Frida] Send async translation failed: {e}")
    
    def send_translation_to_memory(self, address: str, translated: str):
        if not self._script:
            return
        
        try:
            self._script.post({
                "type": "translation",
                "address": address,
                "translated": translated
            })
        except Exception as e:
            print(f"[Frida] Send to memory failed: {e}")
    
    def send_cache(self, translations: Dict[str, str], failed: List[str] = None):
        if not self._script:
            return
        
        try:
            self._script.exports_sync.synccache({
                "translations": translations,
                "failed": failed or []
            })
        except Exception as e:
            print(f"[Frida] Sync cache failed: {e}")
    
    def detach(self):
        self._running = False
        
        if self._script:
            try:
                self._script.unload()
            except:
                pass
            self._script = None
        
        if self._session:
            try:
                self._session.detach()
            except:
                pass
            self._session = None
        
        self._is_attached = False
        print("[Frida] Detached")
    
    @property
    def is_attached(self) -> bool:
        return self._is_attached
    
    def enumerate_processes(self) -> list:
        if not self._import_frida():
            return []
        
        try:
            device = self._get_device()
            processes = device.enumerate_processes()
            return [
                {
                    "pid": p.pid,
                    "name": p.name,
                    "path": getattr(p, 'path', ''),
                }
                for p in processes
            ]
        except Exception as e:
            print(f"[Frida] Enum failed: {e}")
            return []
    
    def find_process(self, name: str) -> Optional[int]:
        processes = self.enumerate_processes()
        name_lower = name.lower()
        
        for proc in processes:
            if name_lower in proc['name'].lower():
                return proc['pid']
        
        return None
