import * as THREE from 'three';

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

const cubeGroup = new THREE.Group();
const geometry = new THREE.BoxGeometry(0.93, 0.93, 0.93);

for (let x = -1; x <= 1; x++) {
    for (let y = -1; y <= 1; y++) {
        for (let z = -1; z <= 1; z++) {
            const m = Array(6).fill(null).map(() =>
                new THREE.MeshBasicMaterial({ color: 0x050505, wireframe: false })
            );
            if (x ===  1) m[0] = new THREE.MeshBasicMaterial({ color: 0x00FFCC });
            if (x === -1) m[1] = new THREE.MeshBasicMaterial({ color: 0xFF0055 });
            if (y ===  1) m[2] = new THREE.MeshBasicMaterial({ color: 0xAA00FF });
            if (y === -1) m[3] = new THREE.MeshBasicMaterial({ color: 0x00FF00 });
            if (z ===  1) m[4] = new THREE.MeshBasicMaterial({ color: 0xFFFF00 });
            if (z === -1) m[5] = new THREE.MeshBasicMaterial({ color: 0xFFFFFF });

            const mesh = new THREE.Mesh(geometry, m);
            mesh.position.set(x, y, z);
            cubeGroup.add(mesh);
        }
    }
}
scene.add(cubeGroup);
camera.position.z = 5;

window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});

function animate() {
    requestAnimationFrame(animate);
    cubeGroup.rotation.x += 0.005;
    cubeGroup.rotation.y += 0.005;
    renderer.render(scene, camera);
}
animate();
