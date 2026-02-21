import zipfile
import shutil
import http.server
import socketserver
import webbrowser
import json
import base64
import os
import sys

PORT = 8090
OUTPUT_DIR = os.path.join('assets', 'renders')
IMPORT_DIR = "import"
TEMP_DIR = "temp_pack"

for folder in [OUTPUT_DIR, IMPORT_DIR]:
    os.makedirs(folder, exist_ok=True)

class RenderRequestHandler(http.server.SimpleHTTPRequestHandler):
    
    def do_GET(self):
        if self.path == '/api/packs':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            packs = [f for f in os.listdir(IMPORT_DIR) if f.endswith(".zip")]
            self.wfile.write(json.dumps({"packs": packs}).encode('utf-8'))
            return
            
        if self.path == '/':
            self.path = '/index.html'
            
        super().do_GET()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
            data = json.loads(post_data.decode('utf-8'))
            
            if self.path == '/api/extract':
                pack_name = data.get('pack')
                if not pack_name:
                    raise ValueError("Не указано имя ресурспака")
                    
                zip_path = os.path.join(IMPORT_DIR, pack_name)
                
                if os.path.exists(TEMP_DIR):
                    shutil.rmtree(TEMP_DIR)
                    
                print(f"Распаковка {pack_name}...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(TEMP_DIR)
                print("Распаковка завершена.")
                    
                models = []
                assets_path = os.path.join(TEMP_DIR, "assets")
                if os.path.exists(assets_path):
                    for namespace in os.listdir(assets_path):
                        namespace_path = os.path.join(assets_path, namespace)
                        if not os.path.isdir(namespace_path):
                            continue
                            
                        models_path = os.path.join(namespace_path, "models")
                        if os.path.exists(models_path):
                            for root, _, files in os.walk(models_path):
                                for file in files:
                                    if file.endswith(".json"):
                                        full_path = os.path.join(root, file)
                                        relative_path = os.path.relpath(full_path, TEMP_DIR)
                                        web_path = os.path.join(TEMP_DIR, relative_path).replace("\\", "/")
                                        models.append(web_path)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"models": models}).encode('utf-8'))

            elif self.path == '/upload_image':
                item_id = data.get('id')
                image_b64 = data.get('image')
                mode = data.get('mode', 'png')
                
                if ',' in image_b64:
                    image_b64 = image_b64.split(',')[1]
                
                file_name = f"{item_id}.{mode}"
                file_path = os.path.join(OUTPUT_DIR, file_name)
                
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                with open(file_path, 'wb') as f:
                    f.write(base64.b64decode(image_b64))
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "path": file_path}).encode('utf-8'))

            else:
                self.send_error(404, "Unknown endpoint")
                
        except Exception as e:
            print(f"Ошибка сервера: {e}")
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        if args and isinstance(args[0], str) and "upload_image" not in args[0]:
            super().log_message(format, *args)

if __name__ == "__main__":
    print(f"Рабочая директория: {os.getcwd()}")
    print(f"Папка сохранения рендеров: {OUTPUT_DIR}")
    print(f"Положите ваши .zip ресурспаки в папку '{IMPORT_DIR}'\n")

    with socketserver.TCPServer(("", PORT), RenderRequestHandler) as httpd:
        url = f"http://localhost:{PORT}/"
        print(f"Сервер запущен {url}")
        
        webbrowser.open(url)
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nСервер остановлен.")
            sys.exit(0)