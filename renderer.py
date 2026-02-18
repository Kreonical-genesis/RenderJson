import zipfile
import shutil
import http.server
import socketserver
import webbrowser
import json
import base64
import os
import sys
import threading
import time

PORT = 8090
MODELS_LIST_FILE = "models_list.json"

OUTPUT_DIR = os.path.join('assets', 'renders')
RENDER_PAGE = 'render_tool.html'
TEMPLATE_FILE = 'render_template.html'

IMPORT_DIR = "import"
TEMP_DIR = "temp_pack"
RENDER_MODE = "png"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

class RenderRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            
            if self.path == '/upload_image':
                item_id = data.get('id')
                image_b64 = data.get('image')
                
                if ',' in image_b64:
                    image_b64 = image_b64.split(',')[1]
                
                file_name = f"{item_id}.png"
                if RENDER_MODE == "gif":
                     file_name = f"{item_id}.gif"

                file_path = os.path.join(OUTPUT_DIR, file_name)
                
                with open(file_path, 'wb') as f:
                    f.write(base64.b64decode(image_b64))
                
                print(f"Saved: {file_name}")
                
                response = {"status": "ok", "path": f"assets/renders/{file_name}"}
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))

            elif self.path == '/save_json':
                self.send_response(200)
                self.end_headers()

            else:
                self.send_error(404, "Unknown endpoint")
                
        except Exception as e:
            print(f"Server error: {e}")
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        message = format % args
        if "POST" in message:
            sys.stderr.write(
                "%s [%s] %s\n" %
                (self.client_address[0],
                self.log_date_time_string(),
                message)
            )

def select_resourcepack():
    if not os.path.exists(IMPORT_DIR):
        print("Import folder not found")
        sys.exit(1)

    zip_files = [f for f in os.listdir(IMPORT_DIR) if f.endswith(".zip")]

    if not zip_files:
        print("No .zip resourcepack found in import/")
        sys.exit(1)

    print("\nAvailable resourcepacks:")
    for i, file in enumerate(zip_files, start=1):
        print(f"{i}. {file}")

    while True:
        try:
            choice = int(input("\nSelect resourcepack number: "))
            if 1 <= choice <= len(zip_files):
                return zip_files[choice - 1]
        except ValueError:
            pass
        print("Invalid selection. Try again.")

def extract_resourcepack(zip_name):
    zip_path = os.path.join(IMPORT_DIR, zip_name)
    print(f"\nSelected: {zip_name}")

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(TEMP_DIR)

    print("Resourcepack extracted.\n")

def select_render_mode():
    print("Render mode:")
    print("1. PNG (static image)")
    print("2. GIF (rotating model)")

    while True:
        choice = input("Select mode number: ")
        if choice == "1":
            return "png"
        elif choice == "2":
            return "gif"
        print("Invalid selection. Try again.")

def collect_models():
    assets_path = os.path.join(TEMP_DIR, "assets")

    if not os.path.exists(assets_path):
        print("Assets folder not found in resourcepack.")
        sys.exit(1)

    model_files = []

    for namespace in os.listdir(assets_path):
        namespace_path = os.path.join(assets_path, namespace)

        if not os.path.isdir(namespace_path):
            continue

        models_path = os.path.join(namespace_path, "models")

        if not os.path.exists(models_path):
            continue

        for root, _, files in os.walk(models_path):
            for file in files:
                if file.endswith(".json"):
                    full_path = os.path.join(root, file)

                    relative_path = os.path.relpath(full_path, TEMP_DIR)
                    web_path = os.path.join(TEMP_DIR, relative_path).replace("\\", "/")

                    model_files.append(web_path)

    print(f"Found {len(model_files)} models across all namespaces.")
    return model_files

def run_server():
    print(f"Render output: {OUTPUT_DIR}")

    with socketserver.TCPServer(("", PORT), RenderRequestHandler) as httpd:
        url = f"http://localhost:{PORT}/{RENDER_PAGE}"
        print(f"Opening {url}")
        
        webbrowser.open(url)
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)

if __name__ == "__main__":
    selected_zip = select_resourcepack()
    RENDER_MODE = select_render_mode()
    extract_resourcepack(selected_zip)
    models = collect_models()

    if not os.path.exists(TEMPLATE_FILE):
        print(f"Error: Template file '{TEMPLATE_FILE}' not found!")
        print("Please ensure render_template.html is in the same directory.")
        sys.exit(1)

    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
        html_template = f.read()

    html_with_mode = html_template.replace("__RENDER_MODE__", RENDER_MODE)
    with open(RENDER_PAGE, 'w', encoding='utf-8') as f:
        f.write(html_with_mode)

    with open(MODELS_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2)

    run_server()