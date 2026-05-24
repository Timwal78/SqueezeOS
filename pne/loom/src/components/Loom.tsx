import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { useAuctionStore, ParticleState } from '../hooks/useAuction'

const PALETTE = {
  obsidian: 0x0a0a0f,
  neonCyan: new THREE.Color(0x00ffe7),
  liquidGold: new THREE.Color(0xffd700),
  challengeRed: new THREE.Color(0xff2d55),
  sponsorViolet: new THREE.Color(0x8b5cf6),
  white: new THREE.Color(0xffffff),
}

const MAX_PARTICLES = 100_000
const MAX_THREADS = 10_000

function stateToColor(state: ParticleState, _tip: number): THREE.Color {
  switch (state) {
    case 1: return PALETTE.challengeRed
    case 2: return PALETTE.neonCyan
    case 3: return PALETTE.liquidGold
    case 4: return PALETTE.white
    default: return new THREE.Color(0x111111)
  }
}

function stateToSize(state: ParticleState, tip: number): number {
  const tipBonus = Math.log10(Math.max(tip, 1)) * 0.5
  switch (state) {
    case 1: return 3 + Math.sin(Date.now() * 0.01) * 1
    case 2: return 5 + tipBonus
    case 3: return 10 + tipBonus * 2
    case 4: return 8
    default: return 1
  }
}

export default function Loom() {
  const canvasRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<{
    renderer: THREE.WebGLRenderer
    scene: THREE.Scene
    camera: THREE.PerspectiveCamera
    particles: THREE.Points
    positions: Float32Array
    colors: Float32Array
    sizes: Float32Array
    alphas: Float32Array
    particleIndex: Map<string, number>
    nextSlot: number
    threads: THREE.LineSegments
    threadPositions: Float32Array
    threadCount: number
    frameId: number
  } | null>(null)

  const particles = useAuctionStore(s => s.particles)

  useEffect(() => {
    if (!canvasRef.current) return

    const container = canvasRef.current
    const width = container.clientWidth
    const height = container.clientHeight

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(PALETTE.obsidian)
    container.appendChild(renderer.domElement)

    // Scene
    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2(PALETTE.obsidian, 0.001)

    // Camera
    const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 10000)
    camera.position.set(0, 0, 800)

    // Subtle camera orbit
    let orbitAngle = 0

    // Particle geometry
    const positions = new Float32Array(MAX_PARTICLES * 3)
    const colors = new Float32Array(MAX_PARTICLES * 3)
    const sizes = new Float32Array(MAX_PARTICLES)
    const alphas = new Float32Array(MAX_PARTICLES)

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
    geometry.setAttribute('alpha', new THREE.BufferAttribute(alphas, 1))

    // Custom shader material — additive blending, radial glow
    const material = new THREE.ShaderMaterial({
      uniforms: { time: { value: 0 } },
      vertexShader: `
        attribute float size;
        attribute float alpha;
        attribute vec3 color;
        varying vec3 vColor;
        varying float vAlpha;
        uniform float time;
        void main() {
          vColor = color;
          vAlpha = alpha;
          vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = size * (600.0 / -mvPos.z);
          gl_Position = projectionMatrix * mvPos;
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        varying float vAlpha;
        void main() {
          vec2 uv = gl_PointCoord - 0.5;
          float r = length(uv);
          if (r > 0.5) discard;
          float glow = 1.0 - smoothstep(0.0, 0.5, r);
          float core = 1.0 - smoothstep(0.0, 0.15, r);
          float intensity = glow * 0.6 + core * 1.5;
          gl_FragColor = vec4(vColor * intensity, vAlpha * glow);
        }
      `,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      transparent: true,
      vertexColors: true,
    })

    const particleSystem = new THREE.Points(geometry, material)
    scene.add(particleSystem)

    // Loom threads (settled bids = gold threads)
    const threadPositions = new Float32Array(MAX_THREADS * 6)
    const threadGeometry = new THREE.BufferGeometry()
    threadGeometry.setAttribute('position', new THREE.BufferAttribute(threadPositions, 3))
    const threadMaterial = new THREE.LineBasicMaterial({
      color: PALETTE.liquidGold,
      transparent: true,
      opacity: 0.25,
      blending: THREE.AdditiveBlending,
    })
    const threads = new THREE.LineSegments(threadGeometry, threadMaterial)
    scene.add(threads)

    // Ambient light for depth
    scene.add(new THREE.AmbientLight(0x0a0a3f, 0.3))

    sceneRef.current = {
      renderer,
      scene,
      camera,
      particles: particleSystem,
      positions,
      colors,
      sizes,
      alphas,
      particleIndex: new Map(),
      nextSlot: 0,
      threads,
      threadPositions,
      threadCount: 0,
      frameId: 0,
    }

    // Animate
    let t = 0
    const animate = () => {
      const ref = sceneRef.current
      if (!ref) return
      ref.frameId = requestAnimationFrame(animate)
      t += 0.016

      // Slow camera orbit
      orbitAngle += 0.0003
      camera.position.x = Math.sin(orbitAngle) * 800
      camera.position.z = Math.cos(orbitAngle) * 800
      camera.lookAt(0, 0, 0)

      material.uniforms.time.value = t

      geometry.attributes.position.needsUpdate = true
      geometry.attributes.color.needsUpdate = true
      geometry.attributes.size.needsUpdate = true
      geometry.attributes.alpha.needsUpdate = true

      renderer.render(scene, camera)
    }
    animate()

    // Resize
    const onResize = () => {
      const w = container.clientWidth
      const h = container.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('resize', onResize)
      cancelAnimationFrame(sceneRef.current?.frameId ?? 0)
      renderer.dispose()
      container.removeChild(renderer.domElement)
      sceneRef.current = null
    }
  }, [])

  // Sync particles from store to Three.js buffers
  useEffect(() => {
    const ref = sceneRef.current
    if (!ref) return

    particles.forEach((p, id) => {
      let slot = ref.particleIndex.get(id)
      if (slot === undefined) {
        slot = ref.nextSlot % MAX_PARTICLES
        ref.nextSlot++
        ref.particleIndex.set(id, slot)

        // Spawn at random position on a sphere
        const theta = Math.random() * Math.PI * 2
        const phi = Math.acos(2 * Math.random() - 1)
        const r = 300 + Math.random() * 100
        ref.positions[slot * 3] = r * Math.sin(phi) * Math.cos(theta)
        ref.positions[slot * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
        ref.positions[slot * 3 + 2] = r * Math.cos(phi)
      }

      const color = stateToColor(p.state, p.tipSats)
      ref.colors[slot * 3] = color.r
      ref.colors[slot * 3 + 1] = color.g
      ref.colors[slot * 3 + 2] = color.b
      ref.sizes[slot] = stateToSize(p.state, p.tipSats)
      ref.alphas[slot] = p.state === 0 ? 0 : 0.8

      // For settled particles (state=3), draw a gold thread toward origin
      if (p.state === 3 && ref.threadCount < MAX_THREADS) {
        const tc = ref.threadCount * 6
        ref.threadPositions[tc] = ref.positions[slot * 3]
        ref.threadPositions[tc + 1] = ref.positions[slot * 3 + 1]
        ref.threadPositions[tc + 2] = ref.positions[slot * 3 + 2]
        ref.threadPositions[tc + 3] = (Math.random() - 0.5) * 200
        ref.threadPositions[tc + 4] = (Math.random() - 0.5) * 200
        ref.threadPositions[tc + 5] = (Math.random() - 0.5) * 200
        ref.threadCount = (ref.threadCount + 1) % MAX_THREADS
        ref.threads.geometry.setDrawRange(0, ref.threadCount * 2)
        ;(ref.threads.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
      }

      // Animate settled particles: move toward center
      if (p.state === 3 || p.state === 4) {
        const speed = p.state === 3 ? 0.05 : 0.03
        ref.positions[slot * 3] *= (1 - speed)
        ref.positions[slot * 3 + 1] *= (1 - speed)
        ref.positions[slot * 3 + 2] *= (1 - speed)
      }
    })
  }, [particles])

  return <div ref={canvasRef} style={{ width: '100%', height: '100%', position: 'absolute', inset: 0 }} />
}
