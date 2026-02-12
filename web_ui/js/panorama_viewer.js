/**
 * Panorama Viewer using Three.js
 * Renders equirectangular panoramas in a 3D sphere
 */

class PanoramaViewer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error('Container not found:', containerId);
            return;
        }

        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.sphere = null;
        this.texture = null;

        // Camera state (lon is relative to panorama image, not true north)
        this.lon = 0;
        this.lat = 0;
        this.fov = 90;

        // Panorama tile origin heading (for converting between image coords and true north)
        // When lon=0, we're looking at centerHeading direction in true north terms
        this.centerHeading = 0;

        // Interaction state
        this.isUserInteracting = false;
        this.onPointerDownMouseX = 0;
        this.onPointerDownMouseY = 0;
        this.onPointerDownLon = 0;
        this.onPointerDownLat = 0;

        // View change callback
        this.onViewChangeCallback = null;

        this.init();
        this.setupEventListeners();
        this.animate();
    }

    init() {
        // Scene
        this.scene = new THREE.Scene();

        // Camera
        this.camera = new THREE.PerspectiveCamera(
            this.fov,
            this.container.clientWidth / this.container.clientHeight,
            0.1,
            1000
        );
        this.camera.position.set(0, 0, 0);

        // Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.container.appendChild(this.renderer.domElement);

        // Sphere geometry (inside-out)
        const geometry = new THREE.SphereGeometry(500, 60, 40);
        geometry.scale(-1, 1, 1); // Flip so we view from inside

        // Default material (placeholder)
        const material = new THREE.MeshBasicMaterial({
            color: 0x1a1a2e,
            side: THREE.FrontSide  // FrontSide because geometry is inverted
        });

        this.sphere = new THREE.Mesh(geometry, material);
        this.scene.add(this.sphere);

        // Handle resize
        window.addEventListener('resize', () => this.onResize());

        // Initialize heading display with initial values
        // Use setTimeout to ensure DOM elements are ready
        setTimeout(() => this.updateHeadingDisplay(), 0);
    }

    setupEventListeners() {
        const canvas = this.renderer.domElement;

        // Mouse events
        canvas.addEventListener('mousedown', (e) => this.onPointerDown(e));
        canvas.addEventListener('mousemove', (e) => this.onPointerMove(e));
        canvas.addEventListener('mouseup', () => this.onPointerUp());
        canvas.addEventListener('mouseleave', () => this.onPointerUp());

        // Touch events
        canvas.addEventListener('touchstart', (e) => this.onTouchStart(e));
        canvas.addEventListener('touchmove', (e) => this.onTouchMove(e));
        canvas.addEventListener('touchend', () => this.onPointerUp());

        // Wheel for FOV
        canvas.addEventListener('wheel', (e) => this.onWheel(e));
    }

    onPointerDown(event) {
        this.isUserInteracting = true;
        this.onPointerDownMouseX = event.clientX;
        this.onPointerDownMouseY = event.clientY;
        this.onPointerDownLon = this.lon;
        this.onPointerDownLat = this.lat;
    }

    onPointerMove(event) {
        if (!this.isUserInteracting) return;

        const movementX = event.clientX - this.onPointerDownMouseX;
        const movementY = event.clientY - this.onPointerDownMouseY;

        // Adjust sensitivity based on FOV
        const sensitivity = this.fov / 500;

        this.lon = this.onPointerDownLon - movementX * sensitivity;
        this.lat = this.onPointerDownLat + movementY * sensitivity;

        // Clamp latitude
        this.lat = Math.max(-85, Math.min(85, this.lat));

        this.updateHeadingDisplay();

        // Trigger real-time view change callback during drag
        if (this.onViewChangeCallback) {
            const viewState = this.getViewState();
            this.onViewChangeCallback(viewState);
        }
    }

    onPointerUp() {
        this.isUserInteracting = false;

        // Trigger view update callback if registered
        if (this.onViewChangeCallback) {
            const viewState = this.getViewState();
            this.onViewChangeCallback(viewState);
        }
    }

    onTouchStart(event) {
        if (event.touches.length === 1) {
            event.preventDefault();
            this.onPointerDown({
                clientX: event.touches[0].clientX,
                clientY: event.touches[0].clientY
            });
        }
    }

    onTouchMove(event) {
        if (event.touches.length === 1) {
            event.preventDefault();
            this.onPointerMove({
                clientX: event.touches[0].clientX,
                clientY: event.touches[0].clientY
            });
        }
    }

    onWheel(event) {
        event.preventDefault();
        this.fov += event.deltaY * 0.05;
        this.fov = Math.max(90, Math.min(90, this.fov));
        this.camera.fov = this.fov;
        this.camera.updateProjectionMatrix();

        // Update heading display on every wheel scroll
        this.updateHeadingDisplay();

        // Trigger view change callback for FOV changes
        if (this.onViewChangeCallback) {
            const viewState = this.getViewState();
            this.onViewChangeCallback(viewState);
        }
    }

    onResize() {
        if (!this.container) return;

        this.camera.aspect = this.container.clientWidth / this.container.clientHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(this.container.clientWidth, this.container.clientHeight);
    }

    animate() {
        requestAnimationFrame(() => this.animate());

        // Update camera direction
        const phi = THREE.MathUtils.degToRad(90 - this.lat);
        const theta = THREE.MathUtils.degToRad(this.lon);

        const x = 500 * Math.sin(phi) * Math.cos(theta);
        const y = 500 * Math.cos(phi);
        const z = 500 * Math.sin(phi) * Math.sin(theta);

        this.camera.lookAt(x, y, z);
        this.renderer.render(this.scene, this.camera);
    }

    /**
     * Load a panorama image
     * @param {string} url - URL to the panorama image
     */
    loadImage(url) {
        const loader = new THREE.TextureLoader();
        loader.load(
            url,
            (texture) => {
                texture.minFilter = THREE.LinearFilter;
                texture.magFilter = THREE.LinearFilter;

                if (this.sphere.material.map) {
                    this.sphere.material.map.dispose();
                }

                this.sphere.material.dispose();
                this.sphere.material = new THREE.MeshBasicMaterial({
                    map: texture,
                    side: THREE.FrontSide  // FrontSide because geometry is inverted
                });

                // Update heading display when new panorama loads
                this.updateHeadingDisplay();
            },
            undefined,
            (error) => {
                console.error('Error loading panorama:', error);
            }
        );
    }

    /**
     * Set the center heading for the current panorama.
     * This is needed to convert between panorama image coordinates and true north.
     * @param {number} centerHeading - The heading at panorama image center (0-360)
     */
    setCenterHeading(centerHeading) {
        this.centerHeading = centerHeading || 0;
        console.log(`[PanoramaViewer] setCenterHeading: ${this.centerHeading}`);
    }

    /**
     * Set the view direction (in true north coordinates)
     * @param {number} heading - Heading in degrees (0-360, true north reference)
     * @param {number} pitch - Pitch in degrees (-85 to 85)
     */
    setView(heading, pitch) {
        // Convert true north heading to panorama image lon
        // When lon=0, we see centerHeading direction
        // To see heading X, we need lon = X - centerHeading
        // Correction: User reported 180 degree offset (front/back reversed)
        this.lon = heading - this.centerHeading + 180;
        // lat: positive = looking UP (camera points above horizon)
        // pitch: positive = looking UP (standard convention)
        this.lat = pitch;
        console.log(`[PanoramaViewer] setView: heading=${heading}, pitch=${pitch}, centerHeading=${this.centerHeading}, lon=${this.lon}`);
        this.updateHeadingDisplay();
    }

    /**
     * Get current view state (in true north coordinates)
     */
    getViewState() {
        // Convert panorama image lon to true north heading
        // heading = lon + centerHeading - 180
        const trueHeading = ((this.lon + this.centerHeading - 180) % 360 + 360) % 360;
        return {
            heading: trueHeading,
            // lat: positive = looking UP, so pitch = lat (no negation)
            pitch: this.lat,
            fov: this.fov
        };
    }

    /**
     * Set callback for view changes (called on pointer up)
     */
    setOnViewChange(callback) {
        this.onViewChangeCallback = callback;
    }

    /**
     * Update heading display in UI
     */
    updateHeadingDisplay() {
        const viewState = this.getViewState();

        // Update heading
        const headingDisplay = document.getElementById('heading-display');
        if (headingDisplay && typeof formatHeadingCompass === 'function') {
            headingDisplay.textContent = `Heading: ${formatHeadingCompass(viewState.heading)}`;
        }

        // Update pitch
        const pitchDisplay = document.getElementById('pitch-display');
        if (pitchDisplay && typeof formatPitch === 'function') {
            pitchDisplay.textContent = `Pitch: ${formatPitch(viewState.pitch)}`;
        }

        // Update FOV
        const fovDisplay = document.getElementById('fov-display');
        if (fovDisplay) {
            fovDisplay.textContent = `FOV: ${Math.round(viewState.fov)}°`;
        }
    }

    /**
     * Dispose of resources
     */
    dispose() {
        if (this.sphere.material.map) {
            this.sphere.material.map.dispose();
        }
        this.sphere.material.dispose();
        this.sphere.geometry.dispose();
        this.renderer.dispose();
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PanoramaViewer;
}
