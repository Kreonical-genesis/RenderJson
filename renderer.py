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
IMPORT_DIR = "import"
TEMP_DIR = "temp_pack"
RENDER_MODE = "png"

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Auto Renderer Tool</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.js"></script>
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
        const RENDER_MODE = "__RENDER_MODE__";
        let scene, camera, renderer, mesh, rotationWrapper;

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

        function resolveTextureUrl(texturePath) {
            let namespace = 'minecraft';
            let path = texturePath;
            if (texturePath.includes(':')) {
                const parts = texturePath.split(':');
                namespace = parts[0];
                path = parts[1];
            }
            return `temp_pack/assets/${namespace}/textures/${path}.png`;
        }

        async function loadModelTextures(model) {
            const textureMap = {};
            const loader = new THREE.TextureLoader();
            
            if (!model.textures) return {};

            let contextDir = "";
            let contextNamespace = "minecraft";

            for(let k in model.textures) {
                const t = model.textures[k];
                if(t && typeof t === 'string' && !t.startsWith('#') && !t.startsWith('items_displayed:') && t.includes('/')) {
                     const parts = t.split(':');
                     if (parts.length > 1) {
                         contextNamespace = parts[0];
                         const p = parts[1];
                         contextDir = p.substring(0, p.lastIndexOf('/')+1);
                     } else {
                         contextNamespace = 'minecraft';
                         const p = parts[0];
                         contextDir = p.substring(0, p.lastIndexOf('/')+1);
                     }
                     break; 
                }
            }

            const resolveRef = (key) => {
                let val = model.textures[key];
                let attempts = 0;
                while (val && val.startsWith('#') && attempts < 10) {
                    val = model.textures[val.substring(1)];
                    attempts++;
                }
                return val;
            };

            const promises = [];
            for (let key in model.textures) {
                const finalPath = resolveRef(key);
                if (finalPath) {
                    let url;
                    if (finalPath.startsWith('items_displayed:')) {
                        const cleanName = finalPath.split(':')[1];
                        const fullPath = contextNamespace + ":" + contextDir + cleanName;
                        url = resolveTextureUrl(fullPath);
                    } else {
                        url = resolveTextureUrl(finalPath);
                    }

                    promises.push(new Promise((resolve) => {
                        loader.load(url, (tex) => {
                            tex.magFilter = THREE.NearestFilter;
                            tex.minFilter = THREE.NearestFilter;
                            tex.colorSpace = THREE.SRGBColorSpace;
                            textureMap['#' + key] = tex;
                            resolve();
                        }, undefined, () => {
                            console.warn("Missing texture:", url);
                            resolve();
                        });
                    }));
                }
            }
            await Promise.all(promises);
            return textureMap;
        }

        async function loadModelWithParents(modelPath, depth = 0) {
            if (depth > 10) {
                throw new Error("Parent recursion limit reached");
            }

            const response = await fetch(modelPath);
            if (!response.ok) throw new Error("Model not found: " + modelPath);
            const model = await response.json();

            if (!model.parent) {
                return model;
            }

            let parentPath;
            const parent = model.parent;

            if (parent.includes(":")) {
                const [namespace, path] = parent.split(":");
                parentPath = `temp_pack/assets/${namespace}/models/${path}.json`;
            } else {
                parentPath = `temp_pack/assets/minecraft/models/${parent}.json`;
            }

            const parentModel = await loadModelWithParents(parentPath, depth + 1);

            return {
                ...parentModel,
                ...model,
                textures: {
                    ...(parentModel.textures || {}),
                    ...(model.textures || {})
                }
            };
        }

        async function createGeometryFromModel(model) {
            const textureMap = await loadModelTextures(model);
            const group = new THREE.Group();
            
            const transparentMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0 });

            if (model.elements) {
                model.elements.forEach(element => {
                    const from = element.from;
                    const to = element.to;
                    const sizeX = (to[0] - from[0]) / 16;
                    const sizeY = (to[1] - from[1]) / 16;
                    const sizeZ = (to[2] - from[2]) / 16;

                    const geometry = new THREE.BoxGeometry(
                        Math.max(sizeX, 0.0001), 
                        Math.max(sizeY, 0.0001), 
                        Math.max(sizeZ, 0.0001)
                    );

                    const uvAttr = new THREE.BufferAttribute(new Float32Array(geometry.attributes.uv.array), 2);
                    geometry.setAttribute('uv', uvAttr);
                    const uvs = uvAttr.array; // теперь изменять безопасно

                    const materials = [];
                    const faceOrder = ['east', 'west', 'up', 'down', 'south', 'north'];

                    if (element.faces) {
                        faceOrder.forEach((faceName, index) => {
                            const face = element.faces[faceName];

                            let assignedMat = transparentMat;
                            if (face && face.texture) {
                                const tex = textureMap[face.texture];
                                if (tex) {
                                    assignedMat = new THREE.MeshStandardMaterial({
                                        map: tex,
                                        transparent: true,
                                        alphaTest: 0.1,
                                        side: THREE.FrontSide,
                                        polygonOffset: true,
                                        polygonOffsetFactor: -1,
                                        polygonOffsetUnits: -1
                                    });
                                }
                            }
                            materials.push(assignedMat);

                            if (face && face.uv) {
                                const uv = face.uv;
                                const u1 = uv[0] / 16;
                                const u2 = uv[2] / 16;
                                const v1 = 1 - (uv[1] / 16);
                                const v2 = 1 - (uv[3] / 16);

                                const corners = [
                                    { u: u1, v: v1 },
                                    { u: u2, v: v1 },
                                    { u: u1, v: v2 },
                                    { u: u2, v: v2 }
                                ];

                                let rotation = face.rotation || 0;
                                let mapOrder = [0, 1, 2, 3];
                                if (rotation === 90)  mapOrder = [2, 0, 3, 1];
                                if (rotation === 180) mapOrder = [3, 2, 1, 0];
                                if (rotation === 270) mapOrder = [1, 3, 0, 2];

                                const offset = index * 8;
                                uvs[offset]     = corners[mapOrder[0]].u; uvs[offset + 1] = corners[mapOrder[0]].v;
                                uvs[offset + 2] = corners[mapOrder[1]].u; uvs[offset + 3] = corners[mapOrder[1]].v;
                                uvs[offset + 4] = corners[mapOrder[2]].u; uvs[offset + 5] = corners[mapOrder[2]].v;
                                uvs[offset + 6] = corners[mapOrder[3]].u; uvs[offset + 7] = corners[mapOrder[3]].v;
                            } else {
                                const offset = index * 8;
                                for(let i=0; i<8; i++) uvs[offset+i] = 0;
                            }
                        });
                        geometry.attributes.uv.needsUpdate = true;
                    } else {
                        for(let i=0; i<6; i++) materials.push(transparentMat);
                    }


                    const cube = new THREE.Mesh(geometry, materials);
                    const posX = ((from[0] + to[0]) / 2) / 16 - 0.5;
                    const posY = ((from[1] + to[1]) / 2) / 16 - 0.5;
                    const posZ = ((from[2] + to[2]) / 2) / 16 - 0.5;
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
            return group;
        }

        async function createGeneratedItem(model) {
            const texturePath = model.textures?.layer0;
            if (!texturePath) throw new Error("No layer0 texture");

            const url = resolveTextureUrl(texturePath);
            const loader = new THREE.TextureLoader();

            const texture = await new Promise((resolve, reject) => {
                loader.load(url, tex => {
                    tex.magFilter = THREE.NearestFilter;
                    tex.minFilter = THREE.NearestFilter;
                    tex.colorSpace = THREE.SRGBColorSpace;
                    resolve(tex);
                }, undefined, reject);
            });

            const geometry = new THREE.BoxGeometry(1, 1, 0.0625);

            const material = new THREE.MeshStandardMaterial({
                map: texture,
                transparent: true,
                alphaTest: 0.1,
                side: THREE.FrontSide
            });

            return new THREE.Mesh(geometry, material);
        }

        async function renderItem(modelPath) {
            let modelData;
            try {
                modelData = await loadModelWithParents(modelPath);
            } catch (e) {
                throw new Error(`Load error: ${e.message}`);
            }

            if (mesh) {
                scene.remove(mesh);
                mesh.traverse(obj => {
                    if (obj.geometry) obj.geometry.dispose();
                    if (obj.material) {
                        if (Array.isArray(obj.material)) {
                            obj.material.forEach(m => m.dispose());
                        } else {
                            obj.material.dispose();
                        }
                    }
                });
                mesh = null;              // <- добавляем
            }

            if (rotationWrapper) {
                scene.remove(rotationWrapper);
                rotationWrapper = null;   // <- добавляем
            }


            if (rotationWrapper) {
                scene.remove(rotationWrapper);
            }

            if (modelData.parent === "item/generated") {
                mesh = await createGeneratedItem(modelData);
                rotationWrapper = new THREE.Group();
                rotationWrapper.add(mesh);
                scene.add(rotationWrapper);
                fitCameraToMesh(mesh);

            } else {

                mesh = await createGeometryFromModel(modelData);
                rotationWrapper = new THREE.Group();
                rotationWrapper.add(mesh);
                scene.add(rotationWrapper);
                fitCameraToMesh(mesh);
            }

            if (RENDER_MODE === "png") {
                renderer.render(scene, camera);
                return renderer.domElement.toDataURL("image/png");
            }

            if (RENDER_MODE === "gif") {
                return await renderGif();
            }
        }

        async function renderGif() {
            mesh.rotation.set(0, 0, 0);
            return new Promise((resolve) => {

                const gif = new GIF({
                    workers: 2,
                    quality: 10,
                    width: 500,
                    height: 500,
                    workerScript: "gif.worker.js"
                });

                const frames = 60; // плавность
                const fullRotation = Math.PI * 2;

                let currentFrame = 0;

                function captureFrame() {
                    const angle = (currentFrame / frames) * fullRotation;
                    rotationWrapper.rotation.y = angle;
                    renderer.render(scene, camera);
                    gif.addFrame(renderer.domElement, { copy: true, delay: 40 });

                    currentFrame++;

                    if (currentFrame < frames) {
                        requestAnimationFrame(captureFrame);
                    } else {
                        gif.on("finished", function(blob) {
                            const reader = new FileReader();
                            reader.onload = function() {
                                resolve(reader.result);
                            };
                            reader.readAsDataURL(blob);
                        });

                        gif.render();
                    }
                }

                captureFrame();
            });
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

        async function startBatchProcess() {
            initScene();
            log("Loading items.json...");
            let models;
            try {
                models = await fetch('models_list.json').then(r => r.json());
            } catch(e) {
                log("Failed to load models_list.json", "error");
                return;
            }

            let total = models.length;
            let processed = 0;

            for (let modelPath of models) {
                processed++;
                updateStatus(`Processing ${processed}/${total}`, (processed/total)*100);

                try {
                    const base64Image = await renderItem(modelPath);

                    await fetch('/upload_image', {
                        method: 'POST',
                        body: JSON.stringify({ 
                            id: modelPath.replaceAll("/", "_").replace(".json",""),
                            image: base64Image 
                        })
                    });

                    log(`[${modelPath}] Success`, "success");

                } catch (e) {
                    log(`[${modelPath}] Error: ${e.message}`, "error");
                }

                await new Promise(r => setTimeout(r, 30));
            }

            document.getElementById('status').textContent = `Done`;
        }

        window.onload = startBatchProcess;
    </script>
</body>
</html>
"""

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

    html_with_mode = HTML_CONTENT.replace("__RENDER_MODE__", RENDER_MODE)
    with open(RENDER_PAGE, 'w', encoding='utf-8') as f:
        f.write(html_with_mode)

    with open(MODELS_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2)

    run_server()