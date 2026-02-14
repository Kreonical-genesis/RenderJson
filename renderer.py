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
ITEMS_FILE = 'items.json'
OUTPUT_DIR = os.path.join('assets', 'renders')
RENDER_PAGE = 'render_tool.html'

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Auto Renderer Tool</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <style>
        body { 
            background: #222; 
            color: #eee; 
            font-family: monospace; 
            display: flex; 
            flex-direction: column; 
            align-items: center; 
            justify-content: center; 
            height: 100vh; 
            margin: 0; 
        }
        #status { font-size: 1.2em; margin-bottom: 20px; }
        #progress { width: 500px; height: 20px; background: #444; border-radius: 10px; overflow: hidden; margin-bottom: 20px;}
        #bar { width: 0%; height: 100%; background: #4CAF50; transition: width 0.3s; }
        canvas { border: 2px solid #555; background-image: linear-gradient(45deg, #333 25%, transparent 25%), linear-gradient(-45deg, #333 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #333 75%), linear-gradient(-45deg, transparent 75%, #333 75%); background-size: 20px 20px; background-position: 0 0, 0 10px, 10px -10px, -10px 0px; }
        .log { height: 150px; width: 500px; overflow-y: auto; background: #111; padding: 10px; border: 1px solid #333; font-size: 12px; margin-top: 10px;}
        .log div { margin-bottom: 2px; }
        .success { color: #4CAF50; }
        .error { color: #f44336; }
        .skip { color: #FF9800; }
    </style>
</head>
<body>
    <div id="status">Init...</div>
    <div id="progress"><div id="bar"></div></div>
    <div id="canvas-container"></div>
    <div class="log" id="log"></div>

    <script>
        let scene, camera, renderer, mesh;

        function initScene() {
            scene = new THREE.Scene();
            camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
            
            const distance = 50;
            const angleY = 225 * Math.PI / 180;
            const angleX = 30 * Math.PI / 180;
            
            camera.position.set(
                distance * Math.sin(angleY) * Math.cos(angleX),
                distance * Math.sin(angleX),
                distance * Math.cos(angleY)
            );
            camera.lookAt(0, 0, 0);

            renderer = new THREE.WebGLRenderer({ 
                antialias: true, 
                alpha: true, 
                preserveDrawingBuffer: true 
            });
            renderer.setSize(500, 500);
            renderer.setClearColor(0x000000, 0);
            
            document.getElementById('canvas-container').appendChild(renderer.domElement);
            scene.add(new THREE.AmbientLight(0xffffff, 0.9));
            const topLight = new THREE.DirectionalLight(0xffffff, 0.5);
            topLight.position.set(5, 20, 5);
            scene.add(topLight);
        }

        function fitCameraToMesh(targetMesh) {
            const box = new THREE.Box3().setFromObject(targetMesh);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());

            targetMesh.position.x -= center.x;
            targetMesh.position.y -= center.y;
            targetMesh.position.z -= center.z;

            const maxDim = Math.max(size.x, size.y, size.z);
            camera.zoom = (2 / (maxDim || 1)) * 0.8; 
            camera.updateProjectionMatrix();
        }

        function createGeometryFromModel(model, textureUrl) {
            return new Promise((resolve, reject) => {
                const group = new THREE.Group();
                const textureLoader = new THREE.TextureLoader();
                
                textureLoader.load(textureUrl, (minecraftTexture) => {
                    minecraftTexture.magFilter = THREE.NearestFilter;
                    minecraftTexture.minFilter = THREE.NearestFilter;

                    if (model.elements) {
                        model.elements.forEach(element => {
                            const from = element.from;
                            const to = element.to;
                            const sizeX = (to[0] - from[0]) / 16;
                            const sizeY = (to[1] - from[1]) / 16;
                            const sizeZ = (to[2] - from[2]) / 16;

                            const geometry = new THREE.BoxGeometry(sizeX, sizeY, sizeZ);
                            
                            if (element.faces) {
                                const uvs = geometry.attributes.uv.array;
                                const faceOrder = ['east', 'west', 'up', 'down', 'south', 'north'];

                                faceOrder.forEach((faceName, index) => {
                                    const face = element.faces[faceName];
                                    if (face && face.uv) {
                                        const uv = face.uv;
                                        const u1 = uv[0] / 16;
                                        const v1 = 1 - (uv[3] / 16); 
                                        const u2 = uv[2] / 16;
                                        const v2 = 1 - (uv[1] / 16);
                                        
                                        const offset = index * 8;
                                        uvs[offset] = u1; uvs[offset + 1] = v2;
                                        uvs[offset + 2] = u2; uvs[offset + 3] = v2;
                                        uvs[offset + 4] = u1; uvs[offset + 5] = v1;
                                        uvs[offset + 6] = u2; uvs[offset + 7] = v1;
                                    }
                                });
                                geometry.attributes.uv.needsUpdate = true;
                            }

                            const material = new THREE.MeshStandardMaterial({
                                map: minecraftTexture,
                                transparent: true,
                                alphaTest: 0.5,
                                side: THREE.DoubleSide
                            });

                            const cube = new THREE.Mesh(geometry, material);
                            const posX = (from[0] + to[0]) / 32 - 0.5;
                            const posY = (from[1] + to[1]) / 32 - 0.5;
                            const posZ = (from[2] + to[2]) / 32 - 0.5;
                            cube.position.set(posX, posY, posZ);

                            if (element.rotation) {
                                const origin = element.rotation.origin;
                                const axis = element.rotation.axis;
                                const angle = (element.rotation.angle || 0) * (Math.PI / 180);
                                
                                const pivotX = origin[0] / 16 - 0.5;
                                const pivotY = origin[1] / 16 - 0.5;
                                const pivotZ = origin[2] / 16 - 0.5;

                                const pivotGroup = new THREE.Group();
                                pivotGroup.position.set(pivotX, pivotY, pivotZ);
                                group.add(pivotGroup);

                                cube.position.set(posX - pivotX, posY - pivotY, posZ - pivotZ);
                                pivotGroup.add(cube);

                                if (axis === 'x') pivotGroup.rotation.x = angle;
                                else if (axis === 'y') pivotGroup.rotation.y = angle;
                                else if (axis === 'z') pivotGroup.rotation.z = angle;
                            } else {
                                group.add(cube);
                            }
                        });
                    }
                    resolve(group);
                }, undefined, (err) => reject(err));
            });
        }

        async function renderItem(modelPath, texturePath) {
            let modelData;
            try {
                const response = await fetch(modelPath);
                if (!response.ok) throw new Error("Model not found");
                modelData = await response.json();
            } catch (e) {
                throw new Error(`Load error: ${e.message}`);
            }

            if (mesh) {
                scene.remove(mesh);
                mesh.traverse((c) => { 
                    if(c.isMesh) { 
                        if(c.geometry) c.geometry.dispose(); 
                        if(c.material) c.material.dispose(); 
                    }
                });
            }

            try {
                mesh = await createGeometryFromModel(modelData, texturePath);
                scene.add(mesh);
                fitCameraToMesh(mesh);
                renderer.render(scene, camera);
                return renderer.domElement.toDataURL('image/png');
            } catch (e) {
                throw new Error(`Three.js error: ${e.message}`);
            }
        }

        const log = (msg, type='normal') => {
            const div = document.createElement('div');
            div.textContent = msg;
            div.className = type;
            document.getElementById('log').prepend(div);
        };

        const updateStatus = (text, percent) => {
            document.getElementById('status').textContent = text;
            document.getElementById('bar').style.width = percent + '%';
        };

        function resolveModelPath(item) {
            const parent = item.parentmodel;
            if (parent && !parent.includes('minecraft:item/generated') && !parent.includes('minecraft:item/handheld') && !parent.includes('builtin/generated')) {
                return parent;
            }
            return item.customModel;
        }

        async function startBatchProcess() {
            initScene();
            log("Loading items.json...");
            let itemsData;
            try {
                itemsData = await fetch('items.json').then(r => r.json());
            } catch(e) {
                log("Failed to load items.json", "error");
                return;
            }

            let queue = [];
            for (let cat in itemsData) {
                itemsData[cat].forEach(item => {
                    queue.push({ category: cat, item: item });
                });
            }

            let total = queue.length;
            let processed = 0;

            for (let entry of queue) {
                const item = entry.item;
                processed++;
                updateStatus(`Processing ${processed}/${total}: ${item.name}`, (processed/total)*100);

                const modelPath = resolveModelPath(item);
                const texturePath = item.customModelTexture;

                if (!modelPath || !texturePath) {
                    log(`[${item.id}] Skipped (missing paths)`, "skip");
                    continue;
                }

                try {
                    const base64Image = await renderItem(modelPath, texturePath);
                    const res = await fetch('/upload_image', {
                        method: 'POST',
                        body: JSON.stringify({ id: item.id, image: base64Image })
                    }).then(r => r.json());

                    if (res.status === 'ok') {
                        item.customIcon = res.path;
                        log(`[${item.id}] Success`, "success");
                    }
                } catch (e) {
                    log(`[${item.id}] Error: ${e.message}`, "error");
                }
                await new Promise(r => setTimeout(r, 50));
            }

            updateStatus("Saving...", 100);
            await fetch('/save_json', {
                method: 'POST',
                body: JSON.stringify({ items: itemsData })
            });
            document.getElementById('status').textContent = `Done`;
        }

        window.onload = startBatchProcess;
    </script>
</body>
</html>
"""

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

with open(RENDER_PAGE, 'w', encoding='utf-8') as f:
    f.write(HTML_CONTENT)

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
                updated_items = data.get('items')
                print("Updating items.json...")
                with open(ITEMS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(updated_items, f, ensure_ascii=False, indent=2)
                
                print("Complete")
                self.send_response(200)
                self.end_headers()
                
                def shutdown():
                    time.sleep(2)
                    print("Server stopped(render)")
                    os._exit(0)
                threading.Thread(target=shutdown).start()

            else:
                self.send_error(404, "Unknown endpoint")
                
        except Exception as e:
            print(f"Server error: {e}")
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        if "POST" in args[0]:
             sys.stderr.write("%s [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format%args))

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
    if not os.path.exists(ITEMS_FILE):
        print(f"Error: {ITEMS_FILE} not found")
        sys.exit(1)
    
    run_server()