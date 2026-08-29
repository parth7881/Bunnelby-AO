import * as THREE from 'three';
import { AO_CORE_PALETTE, AO_CORE_QUALITY, normalizeCoreProps } from './aoCoreConfig';

const TAU = Math.PI * 2;

function damp(current, target, speed, delta) {
  return THREE.MathUtils.lerp(current, target, 1 - Math.exp(-speed * delta));
}

function makeGlowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  const glow = context.createRadialGradient(64, 64, 0, 64, 64, 64);
  glow.addColorStop(0, 'rgba(255,255,240,1)');
  glow.addColorStop(0.1, 'rgba(255,226,146,.96)');
  glow.addColorStop(0.32, 'rgba(255,153,57,.42)');
  glow.addColorStop(0.64, 'rgba(34,191,234,.10)');
  glow.addColorStop(1, 'rgba(0,0,0,0)');
  context.fillStyle = glow;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

class OrbitalCurve extends THREE.Curve {
  constructor(radius, flatten, start, span, wobble = 0) {
    super();
    this.radius = radius;
    this.flatten = flatten;
    this.start = start;
    this.span = span;
    this.wobble = wobble;
  }

  getPoint(t, target = new THREE.Vector3()) {
    const angle = this.start + this.span * t;
    return target.set(
      Math.cos(angle) * this.radius,
      Math.sin(angle) * this.radius * this.flatten,
      Math.sin(angle * 2.0 + 0.45) * this.wobble
    );
  }
}

function createTube({ radius, flatten, start, span, wobble, color, opacity, thickness = 0.009 }) {
  const curve = new OrbitalCurve(radius, flatten, start, span, wobble);
  const geometry = new THREE.TubeGeometry(curve, Math.max(36, Math.floor(span * 18)), thickness, 5, false);
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    depthTest: true,
    toneMapped: false
  });
  return new THREE.Mesh(geometry, material);
}

function createOrbitSystem(root) {
  const specifications = [
    { r: 1.06, f: 0.37, start: 0.12, span: 5.68, wobble: 0.08, rotation: [0.48, -0.22, -0.18], color: AO_CORE_PALETTE.cyan, opacity: 0.73, speed: 0.13, react: -0.055 },
    { r: 0.94, f: 0.52, start: 0.76, span: 5.04, wobble: 0.04, rotation: [-0.68, 0.36, 0.98], color: AO_CORE_PALETTE.ice, opacity: 0.48, speed: -0.18, react: 0.045 },
    { r: 0.83, f: 0.42, start: 2.02, span: 4.78, wobble: 0.06, rotation: [0.18, 0.92, -0.72], color: AO_CORE_PALETTE.gold, opacity: 0.62, speed: 0.22, react: -0.035 },
    { r: 1.34, f: 0.28, start: 0.48, span: 4.08, wobble: 0.11, rotation: [1.12, -0.34, 0.28], color: AO_CORE_PALETTE.cyan, opacity: 0.32, speed: -0.08, react: 0.075 },
    { r: 1.5, f: 0.45, start: 2.72, span: 2.86, wobble: 0.07, rotation: [-0.38, -0.82, 0.58], color: AO_CORE_PALETTE.blue, opacity: 0.28, speed: 0.065, react: 0.1 },
    { r: 1.7, f: 0.22, start: 4.12, span: 1.92, wobble: 0.12, rotation: [0.84, 0.12, -0.36], color: AO_CORE_PALETTE.gold, opacity: 0.34, speed: -0.045, react: 0.12 },
    { r: 1.82, f: 0.62, start: 0.64, span: 1.38, wobble: 0.03, rotation: [-0.78, 0.18, -0.92], color: AO_CORE_PALETTE.ice, opacity: 0.24, speed: 0.038, react: 0.14 }
  ];

  return specifications.map((specification, index) => {
    const plane = new THREE.Group();
    plane.rotation.set(...specification.rotation);
    const tube = createTube({
      radius: specification.r,
      flatten: specification.f,
      start: specification.start,
      span: specification.span,
      wobble: specification.wobble,
      color: specification.color,
      opacity: specification.opacity,
      thickness: index < 3 ? 0.012 : 0.008
    });
    plane.add(tube);
    root.add(plane);
    return { ...specification, plane, tube, phase: index * 0.73 };
  });
}

function createParticleField(count) {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  const tints = new Float32Array(count);

  for (let index = 0; index < count; index += 1) {
    const seed = Math.random();
    const radius = 0.62 + Math.pow(Math.random(), 0.68) * 1.5;
    const theta = Math.random() * TAU;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
    positions[index * 3 + 1] = radius * Math.cos(phi) * (0.62 + seed * 0.22);
    positions[index * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
    seeds[index] = seed;
    tints[index] = Math.random();
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));
  geometry.setAttribute('aTint', new THREE.BufferAttribute(tints, 1));

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uAudio: { value: 0 },
      uListening: { value: 0 },
      uThinking: { value: 0 },
      uSpeaking: { value: 0 },
      uReduced: { value: 0 },
      uPointScale: { value: 1 }
    },
    vertexShader: `
      attribute float aSeed;
      attribute float aTint;
      varying float vAlpha;
      varying float vTint;
      uniform float uTime;
      uniform float uAudio;
      uniform float uListening;
      uniform float uThinking;
      uniform float uSpeaking;
      uniform float uReduced;
      uniform float uPointScale;

      mat2 rotate2d(float angle) {
        return mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
      }

      void main() {
        vec3 p = position;
        float motion = 1.0 - uReduced * 0.94;
        float radius = length(p);
        float idleTurn = uTime * (0.025 + aSeed * 0.018) * motion;
        p.xz = rotate2d(idleTurn) * p.xz;
        p.xy = rotate2d(-idleTurn * 0.42) * p.xy;

        float inwardWave = sin(radius * 10.0 + aSeed * 5.0 - uTime * 4.2 * motion) * 0.5 + 0.5;
        p *= 1.0 - uListening * (0.028 + inwardWave * (0.035 + uAudio * 0.13));

        float computeTurn = uTime * (0.52 + aSeed * 0.35) * uThinking * motion;
        p.xz = rotate2d(computeTurn) * p.xz;
        p.y *= 1.0 - uThinking * (0.12 + aSeed * 0.12);

        float outwardWave = sin(radius * 11.0 - uTime * 5.7 * motion + aSeed * 2.4) * 0.5 + 0.5;
        p *= 1.0 + uSpeaking * (0.022 + outwardWave * (0.04 + uAudio * 0.14));

        vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        float stateEnergy = uListening * 0.35 + uThinking * 0.58 + uSpeaking * (0.55 + uAudio);
        gl_PointSize = (1.2 + aSeed * 2.25 + stateEnergy * 1.15) * uPointScale * (6.0 / -mvPosition.z);
        vAlpha = 0.24 + aSeed * 0.48 + stateEnergy * 0.1;
        vTint = aTint;
      }
    `,
    fragmentShader: `
      varying float vAlpha;
      varying float vTint;
      uniform float uSpeaking;
      uniform float uAudio;

      void main() {
        vec2 center = gl_PointCoord - 0.5;
        float distanceToCenter = length(center);
        if (distanceToCenter > 0.5) discard;
        float glow = smoothstep(0.5, 0.0, distanceToCenter);
        glow *= glow;
        vec3 cyan = vec3(0.31, 0.86, 1.0);
        vec3 ice = vec3(0.82, 0.98, 1.0);
        vec3 gold = vec3(1.0, 0.67, 0.24);
        vec3 color = mix(cyan, ice, smoothstep(0.62, 0.94, vTint));
        color = mix(color, gold, step(0.88, vTint) + uSpeaking * uAudio * 0.22);
        gl_FragColor = vec4(color, glow * vAlpha);
      }
    `
  });

  return new THREE.Points(geometry, material);
}

function createBackgroundDust(count) {
  const positions = new Float32Array(count * 3);
  for (let index = 0; index < count; index += 1) {
    const angle = Math.random() * TAU;
    const radius = 2.4 + Math.random() * 2.6;
    positions[index * 3] = Math.cos(angle) * radius;
    positions[index * 3 + 1] = (Math.random() - 0.5) * 4.2;
    positions[index * 3 + 2] = Math.sin(angle) * radius - 1.4;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color: AO_CORE_PALETTE.cyan,
    size: 0.012,
    transparent: true,
    opacity: 0.1,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true
  });
  return new THREE.Points(geometry, material);
}

function createNucleus(root, glowTexture) {
  const assembly = new THREE.Group();
  root.add(assembly);

  const occluder = new THREE.Mesh(
    new THREE.SphereGeometry(0.48, 32, 24),
    new THREE.MeshBasicMaterial({ color: 0x130b03, transparent: true, opacity: 0.62, depthWrite: true })
  );
  assembly.add(occluder);

  const coreMaterial = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uAudio: { value: 0 },
      uListening: { value: 0 },
      uThinking: { value: 0 },
      uSpeaking: { value: 0 },
      uReduced: { value: 0 }
    },
    vertexShader: `
      varying vec3 vNormal;
      varying vec3 vView;
      uniform float uTime;
      uniform float uAudio;
      uniform float uSpeaking;
      uniform float uThinking;
      uniform float uReduced;

      void main() {
        vNormal = normalize(normalMatrix * normal);
        float motion = 1.0 - uReduced * 0.96;
        float ripple = sin(position.y * 16.0 + uTime * 2.2 * motion) * 0.012;
        ripple += sin(position.x * 21.0 - uTime * 1.6 * motion) * 0.008;
        float energy = uThinking * 0.012 + uSpeaking * uAudio * 0.028;
        vec3 displaced = position + normal * (ripple + energy);
        vec4 mvPosition = modelViewMatrix * vec4(displaced, 1.0);
        vView = -mvPosition.xyz;
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      varying vec3 vNormal;
      varying vec3 vView;
      uniform float uTime;
      uniform float uAudio;
      uniform float uListening;
      uniform float uThinking;
      uniform float uSpeaking;

      void main() {
        float facing = abs(dot(normalize(vNormal), normalize(vView)));
        float fresnel = pow(1.0 - facing, 2.25);
        float bands = sin((vNormal.y + vNormal.x * 0.35) * 18.0 + uTime * (1.1 + uThinking * 2.4)) * 0.5 + 0.5;
        vec3 amber = vec3(1.0, 0.34, 0.055);
        vec3 gold = vec3(1.0, 0.77, 0.27);
        vec3 whiteHot = vec3(1.0, 0.98, 0.78);
        vec3 color = mix(amber, gold, bands * 0.55 + facing * 0.28);
        color = mix(color, whiteHot, clamp(uThinking * 0.25 + uSpeaking * (0.36 + uAudio * 0.36), 0.0, 0.78));
        float innerHeat = smoothstep(0.91, 0.998, facing);
        innerHeat *= innerHeat;
        float sourceEnergy = 0.56 + uListening * 0.08 + uThinking * 0.27 + uSpeaking * (0.3 + uAudio * 0.14);
        color = mix(color, whiteHot, innerHeat * clamp(sourceEnergy, 0.0, 1.0));
        float alpha = 0.62 + fresnel * 0.32 + uListening * 0.06 + uThinking * 0.16 + uSpeaking * (0.12 + uAudio * 0.18);
        gl_FragColor = vec4(color, alpha);
      }
    `
  });
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.43, 5), coreMaterial);
  core.renderOrder = 5;
  assembly.add(core);

  const latticeMaterial = new THREE.MeshBasicMaterial({
    color: AO_CORE_PALETTE.gold,
    wireframe: true,
    transparent: true,
    opacity: 0.23,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  const lattice = new THREE.Mesh(new THREE.IcosahedronGeometry(0.57, 2), latticeMaterial);
  assembly.add(lattice);

  const innerLatticeMaterial = new THREE.MeshBasicMaterial({
    color: AO_CORE_PALETTE.ice,
    wireframe: true,
    transparent: true,
    opacity: 0.17,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  const innerLattice = new THREE.Mesh(new THREE.OctahedronGeometry(0.69, 2), innerLatticeMaterial);
  innerLattice.rotation.set(0.5, 0.3, 0.2);
  assembly.add(innerLattice);

  const glowMaterial = new THREE.SpriteMaterial({
    map: glowTexture,
    color: AO_CORE_PALETTE.gold,
    transparent: true,
    opacity: 0.88,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    depthTest: false,
    toneMapped: false
  });
  const glow = new THREE.Sprite(glowMaterial);
  glow.scale.setScalar(2.0);
  glow.renderOrder = 20;
  assembly.add(glow);

  const hotPointMaterial = glowMaterial.clone();
  hotPointMaterial.color.setHex(AO_CORE_PALETTE.white);
  hotPointMaterial.opacity = 0.9;
  const hotPoint = new THREE.Sprite(hotPointMaterial);
  hotPoint.scale.setScalar(0.36);
  hotPoint.renderOrder = 21;
  assembly.add(hotPoint);

  return { assembly, core, coreMaterial, lattice, latticeMaterial, innerLattice, innerLatticeMaterial, glow, glowMaterial, hotPoint, hotPointMaterial };
}

function createWaveShells(root, color) {
  return Array.from({ length: 3 }, (_, index) => {
    const material = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0,
      wireframe: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: true
    });
    const mesh = new THREE.Mesh(new THREE.IcosahedronGeometry(0.73, 2), material);
    mesh.userData.phase = index / 3;
    root.add(mesh);
    return mesh;
  });
}

function createEnergyNeedles(root) {
  const points = [];
  for (let index = 0; index < 28; index += 1) {
    const phi = Math.acos(2 * Math.random() - 1);
    const theta = Math.random() * TAU;
    const direction = new THREE.Vector3(
      Math.sin(phi) * Math.cos(theta),
      Math.cos(phi),
      Math.sin(phi) * Math.sin(theta)
    );
    const inner = direction.clone().multiplyScalar(0.48 + Math.random() * 0.16);
    const outer = direction.clone().multiplyScalar(0.75 + Math.random() * 0.55);
    points.push(inner, outer);
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color: AO_CORE_PALETTE.gold,
    transparent: true,
    opacity: 0.06,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  const lines = new THREE.LineSegments(geometry, material);
  root.add(lines);
  return lines;
}

function createNodeCloud(root, glowTexture) {
  const material = new THREE.SpriteMaterial({
    map: glowTexture,
    color: AO_CORE_PALETTE.ice,
    transparent: true,
    opacity: 0.62,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    depthTest: true
  });
  const group = new THREE.Group();
  const nodes = [];
  for (let index = 0; index < AO_CORE_QUALITY.orbitNodes; index += 1) {
    const nodeMaterial = index % 7 === 0 ? material.clone() : material;
    if (index % 7 === 0) nodeMaterial.color.setHex(AO_CORE_PALETTE.gold);
    const node = new THREE.Sprite(nodeMaterial);
    const angle = (index / AO_CORE_QUALITY.orbitNodes) * TAU + (index % 3) * 0.37;
    const radius = 0.78 + (index % 5) * 0.19;
    node.position.set(
      Math.cos(angle) * radius,
      Math.sin(angle) * radius * (0.35 + (index % 3) * 0.1),
      Math.sin(angle * 1.7) * 0.72
    );
    node.scale.setScalar(index % 7 === 0 ? 0.09 : 0.045);
    group.add(node);
    nodes.push(node);
  }
  group.rotation.set(0.4, -0.3, 0.1);
  root.add(group);
  return { group, nodes, material };
}

export function createAOCoreScene(container, initialProps = {}) {
  let props = normalizeCoreProps(initialProps);
  let disposed = false;
  let animationFrame = 0;
  let width = 1;
  let height = 1;
  let elapsed = 0;
  let previous = performance.now();
  let smoothedAudio = props.audioLevel;
  const stateMix = { listening: 0, thinking: 0, speaking: 0 };
  let reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, AO_CORE_QUALITY.pixelRatio));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  renderer.domElement.className = 'ao-core__canvas';
  renderer.domElement.setAttribute('aria-hidden', 'true');
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 30);
  camera.position.set(0, 0, 6.15);

  const root = new THREE.Group();
  root.rotation.set(-0.1, 0.08, 0.02);
  scene.add(root);

  const glowTexture = makeGlowTexture();
  const atmosphereMaterial = new THREE.SpriteMaterial({
    map: glowTexture,
    color: AO_CORE_PALETTE.cyan,
    transparent: true,
    opacity: 0.14,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    depthTest: false
  });
  const atmosphere = new THREE.Sprite(atmosphereMaterial);
  atmosphere.scale.setScalar(5.3);
  atmosphere.position.z = -0.4;
  root.add(atmosphere);

  const rings = createOrbitSystem(root);
  const particles = createParticleField(AO_CORE_QUALITY.particles);
  root.add(particles);
  const backgroundDust = createBackgroundDust(AO_CORE_QUALITY.backgroundParticles);
  scene.add(backgroundDust);
  const nucleus = createNucleus(root, glowTexture);
  const speakingShells = createWaveShells(root, AO_CORE_PALETTE.gold);
  const listeningShells = createWaveShells(root, AO_CORE_PALETTE.cyan);
  const energyNeedles = createEnergyNeedles(root);
  const nodeCloud = createNodeCloud(root, glowTexture);

  const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const onMotionPreference = (event) => { reducedMotion = event.matches; };
  mediaQuery.addEventListener?.('change', onMotionPreference);

  function resize(nextWidth, nextHeight) {
    if (disposed) return;
    width = Math.max(1, Math.floor(nextWidth));
    height = Math.max(1, Math.floor(nextHeight));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function update(nextProps) {
    props = normalizeCoreProps(nextProps);
  }

  function render(now) {
    if (disposed) return;
    const delta = Math.min(0.05, Math.max(0.001, (now - previous) / 1000));
    previous = now;
    elapsed += delta;

    const targetListening = props.state === 'listening' ? 1 : 0;
    const targetThinking = props.state === 'thinking' ? 1 : 0;
    const targetSpeaking = props.state === 'speaking' ? 1 : 0;
    stateMix.listening = damp(stateMix.listening, targetListening, 4.6, delta);
    stateMix.thinking = damp(stateMix.thinking, targetThinking, 4.2, delta);
    stateMix.speaking = damp(stateMix.speaking, targetSpeaking, 5.0, delta);
    smoothedAudio = damp(smoothedAudio, props.audioLevel, 12, delta);

    const motion = reducedMotion ? 0.035 : 1;
    const activity = stateMix.listening * 0.55 + stateMix.thinking * 1.45 + stateMix.speaking * 0.85;
    root.rotation.y += delta * (0.026 + activity * 0.018) * motion;
    root.rotation.x = -0.1 + Math.sin(elapsed * 0.19) * 0.035 * motion;
    root.rotation.z = Math.sin(elapsed * 0.13) * 0.025 * motion;

    rings.forEach((ring, index) => {
      const thinkingDirection = index % 2 === 0 ? 1 : -1;
      const speed = ring.speed + stateMix.thinking * thinkingDirection * (0.38 + index * 0.025);
      ring.plane.rotation.z += delta * speed * motion;
      const listeningScale = 1 + stateMix.listening * (ring.react + Math.sin(elapsed * 4.2 + ring.phase) * smoothedAudio * 0.045);
      const speakingScale = 1 + stateMix.speaking * (0.018 + Math.sin(elapsed * 5.1 - ring.phase) * smoothedAudio * 0.035);
      ring.plane.scale.setScalar(listeningScale * speakingScale);
      ring.tube.material.opacity = ring.opacity * (1 + stateMix.thinking * 0.42 + stateMix.speaking * smoothedAudio * 0.28);
    });

    const particleUniforms = particles.material.uniforms;
    particleUniforms.uTime.value = elapsed;
    particleUniforms.uAudio.value = smoothedAudio;
    particleUniforms.uListening.value = stateMix.listening;
    particleUniforms.uThinking.value = stateMix.thinking;
    particleUniforms.uSpeaking.value = stateMix.speaking;
    particleUniforms.uReduced.value = reducedMotion ? 1 : 0;
    particleUniforms.uPointScale.value = props.size === 'docked' ? 0.82 : 1;
    particles.visible = props.size !== 'docked' || width > 150;

    const coreUniforms = nucleus.coreMaterial.uniforms;
    coreUniforms.uTime.value = elapsed;
    coreUniforms.uAudio.value = smoothedAudio;
    coreUniforms.uListening.value = stateMix.listening;
    coreUniforms.uThinking.value = stateMix.thinking;
    coreUniforms.uSpeaking.value = stateMix.speaking;
    coreUniforms.uReduced.value = reducedMotion ? 1 : 0;

    const breath = reducedMotion ? 1 : 1 + Math.sin(elapsed * 1.18) * 0.018;
    const nucleusScale = breath + stateMix.thinking * 0.045 + stateMix.speaking * (0.035 + smoothedAudio * 0.09);
    nucleus.assembly.scale.setScalar(nucleusScale);
    nucleus.core.rotation.y += delta * (0.12 + stateMix.thinking * 1.25) * motion;
    nucleus.core.rotation.x -= delta * (0.08 + stateMix.thinking * 0.72) * motion;
    nucleus.lattice.rotation.y -= delta * (0.16 + stateMix.thinking * 0.62) * motion;
    nucleus.lattice.rotation.z += delta * (0.09 + stateMix.thinking * 0.38) * motion;
    nucleus.innerLattice.rotation.x += delta * (0.1 + stateMix.thinking * 0.82) * motion;
    nucleus.innerLattice.rotation.y -= delta * (0.12 + stateMix.thinking * 0.66) * motion;
    nucleus.latticeMaterial.opacity = 0.2 + stateMix.thinking * 0.24 + stateMix.speaking * smoothedAudio * 0.16;
    nucleus.innerLatticeMaterial.opacity = 0.14 + stateMix.listening * 0.09 + stateMix.thinking * 0.2;
    nucleus.glowMaterial.opacity = 0.72 + stateMix.listening * 0.03 + stateMix.thinking * 0.18 + stateMix.speaking * (0.08 + smoothedAudio * 0.18);
    const glowScale = 1.82 + stateMix.thinking * 0.22 + stateMix.speaking * (0.18 + smoothedAudio * 0.42);
    nucleus.glow.scale.setScalar(glowScale);
    nucleus.hotPointMaterial.opacity = Math.min(1, 0.92 + stateMix.listening * 0.02 + stateMix.thinking * 0.06 + stateMix.speaking * (0.06 + smoothedAudio * 0.08));
    nucleus.hotPoint.scale.setScalar(0.34 + stateMix.listening * 0.015 + stateMix.thinking * 0.04 + stateMix.speaking * (0.08 + smoothedAudio * 0.2));

    speakingShells.forEach((shell, index) => {
      const phase = (elapsed * (0.42 + smoothedAudio * 0.48) + index / speakingShells.length) % 1;
      shell.scale.setScalar(0.78 + phase * (1.05 + smoothedAudio * 0.52));
      shell.material.opacity = stateMix.speaking * (1 - phase) * (0.025 + smoothedAudio * 0.19);
      shell.rotation.y += delta * (0.1 + index * 0.06) * motion;
    });

    listeningShells.forEach((shell, index) => {
      const phase = (elapsed * (0.34 + smoothedAudio * 0.42) + index / listeningShells.length) % 1;
      shell.scale.setScalar(2.0 - phase * (1.06 + smoothedAudio * 0.22));
      shell.material.opacity = stateMix.listening * phase * (0.018 + smoothedAudio * 0.12);
      shell.rotation.x -= delta * (0.08 + index * 0.05) * motion;
    });

    energyNeedles.rotation.y -= delta * (0.05 + stateMix.thinking * 0.72) * motion;
    energyNeedles.rotation.z += delta * stateMix.thinking * 0.31 * motion;
    energyNeedles.material.opacity = 0.035 + stateMix.thinking * 0.24 + stateMix.speaking * smoothedAudio * 0.18;
    const needleScale = 0.9 + stateMix.speaking * smoothedAudio * 0.28;
    energyNeedles.scale.setScalar(needleScale);

    nodeCloud.group.rotation.y += delta * (0.06 + stateMix.thinking * 0.5) * motion;
    nodeCloud.group.rotation.z -= delta * (0.03 + stateMix.thinking * 0.28) * motion;
    nodeCloud.group.scale.setScalar(1 - stateMix.listening * (0.035 + smoothedAudio * 0.06) + stateMix.speaking * smoothedAudio * 0.07);
    nodeCloud.material.opacity = 0.48 + stateMix.listening * 0.2 + stateMix.thinking * 0.24;

    atmosphere.material.opacity = 0.09 + stateMix.listening * 0.03 + stateMix.thinking * 0.045 + stateMix.speaking * (0.04 + smoothedAudio * 0.05);
    atmosphere.scale.setScalar(4.9 + stateMix.speaking * smoothedAudio * 0.45);
    backgroundDust.rotation.y += delta * 0.003 * motion;
    renderer.render(scene, camera);
    animationFrame = window.requestAnimationFrame(render);
  }

  resize(container.clientWidth, container.clientHeight);
  animationFrame = window.requestAnimationFrame(render);

  return {
    update,
    resize,
    dispose() {
      if (disposed) return;
      disposed = true;
      window.cancelAnimationFrame(animationFrame);
      mediaQuery.removeEventListener?.('change', onMotionPreference);
      const geometries = new Set();
      const materials = new Set();
      scene.traverse((object) => {
        if (object.geometry) geometries.add(object.geometry);
        if (Array.isArray(object.material)) object.material.forEach((material) => materials.add(material));
        else if (object.material) materials.add(object.material);
      });
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
      glowTexture.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    }
  };
}
