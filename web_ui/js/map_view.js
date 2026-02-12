/**
 * Map View using Leaflet.js
 * Displays 2D map with trajectory and markers
 */

class MapView {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error('Map container not found:', containerId);
            return;
        }

        this.map = null;
        this.markers = [];
        this.trajectoryLine = null;
        this.trajectoryPoints = [];
        this.agentMarker = null;

        this.init();
    }

    init() {
        // Initialize Leaflet map
        this.map = L.map(this.container.id, {
            center: [51.505, -0.09],
            zoom: 18,
            zoomControl: true,
            maxZoom: 19
        });

        // Add tile layer (OpenStreetMap)
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(this.map);

        // Custom marker icons
        this.icons = {
            spawn: L.divIcon({
                className: 'custom-marker',
                html: '<div style="background: #10b981; width: 16px; height: 16px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            }),
            current: L.divIcon({
                className: 'custom-marker',
                html: '<div style="background: #6366f1; width: 20px; height: 20px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            }),
            target: L.divIcon({
                className: 'custom-marker',
                html: '<div style="background: #ef4444; width: 16px; height: 16px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            }),
            step: L.divIcon({
                className: 'custom-marker',
                html: '<div style="background: #8b5cf6; width: 8px; height: 8px; border-radius: 50%; border: 2px solid white;"></div>',
                iconSize: [8, 8],
                iconAnchor: [4, 4]
            })
        };
    }

    /**
     * Set map center
     * @param {number} lat - Latitude
     * @param {number} lng - Longitude
     * @param {number} zoom - Optional zoom level
     */
    setCenter(lat, lng, zoom = null) {
        if (!this.map || lat === null || lng === null) return;

        if (zoom !== null) {
            this.map.setView([lat, lng], zoom);
        } else {
            this.map.panTo([lat, lng]);
        }
    }

    /**
     * Add a marker to the map
     * @param {number} lat - Latitude
     * @param {number} lng - Longitude
     * @param {string} label - Marker label/popup content
     * @param {string} type - Marker type: 'spawn', 'current', 'target', 'step'
     */
    addMarker(lat, lng, label = '', type = 'step') {
        if (!this.map || lat === null || lng === null) return;

        const icon = this.icons[type] || this.icons.step;
        const marker = L.marker([lat, lng], { icon }).addTo(this.map);

        if (label) {
            marker.bindPopup(label);
        }

        this.markers.push(marker);
        return marker;
    }

    /**
     * Clear all markers
     */
    clearMarkers() {
        this.markers.forEach(marker => marker.remove());
        this.markers = [];
    }

    /**
     * Add a point to the trajectory line
     * @param {number} lat - Latitude
     * @param {number} lng - Longitude
     */
    addTrajectoryPoint(lat, lng) {
        if (lat === null || lng === null) return;

        this.trajectoryPoints.push([lat, lng]);
        this.updateTrajectoryLine();
    }

    /**
     * Set the full trajectory
     * @param {Array} points - Array of [lat, lng] pairs
     */
    setTrajectory(points) {
        this.trajectoryPoints = points.filter(p => p[0] !== null && p[1] !== null);
        this.updateTrajectoryLine();
    }

    /**
     * Update the trajectory line on the map
     */
    updateTrajectoryLine() {
        if (!this.map) return;

        // Remove existing line
        if (this.trajectoryLine) {
            this.trajectoryLine.remove();
        }

        if (this.trajectoryPoints.length < 2) return;

        // Create new line
        this.trajectoryLine = L.polyline(this.trajectoryPoints, {
            color: '#6366f1',
            weight: 3,
            opacity: 0.8,
            dashArray: '5, 10'
        }).addTo(this.map);
    }

    /**
     * Clear the trajectory
     */
    clearTrajectory() {
        this.trajectoryPoints = [];
        if (this.trajectoryLine) {
            this.trajectoryLine.remove();
            this.trajectoryLine = null;
        }
    }

    /**
     * Update or create the agent position marker
     * @param {number} lat - Latitude
     * @param {number} lng - Longitude
     * @param {number} heading - Direction in degrees (0=North)
     */
    updateAgentMarker(lat, lng, heading = 0) {
        if (!this.map || lat === null || lng === null) return;

        // Remove existing agent marker if any
        if (this.agentMarker) {
            this.agentMarker.remove();
        }

        // Create agent marker with direction arrow
        const agentIcon = L.divIcon({
            className: 'agent-marker',
            html: `<div style="position: relative; width: 24px; height: 32px;">
                <div style="position: absolute; top: 12px; left: 2px; background: #6366f1; width: 20px; height: 20px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>
                <div style="position: absolute; top: 0; left: 6px; transform: rotate(${heading}deg); transform-origin: center 22px;">
                    <div style="width: 0; height: 0; border-left: 6px solid transparent; border-right: 6px solid transparent; border-bottom: 10px solid #6366f1;"></div>
                </div>
            </div>`,
            iconSize: [24, 32],
            iconAnchor: [12, 22]
        });

        this.agentMarker = L.marker([lat, lng], { icon: agentIcon, zIndexOffset: 1000 }).addTo(this.map);
    }

    /**
     * Add a direction arrow at a point
     * @param {number} lat - Latitude
     * @param {number} lng - Longitude
     * @param {number} heading - Direction in degrees (0=North)
     */
    addDirectionArrow(lat, lng, heading) {
        if (!this.map || lat === null || lng === null) return;

        // Create arrow icon rotated by heading
        const arrowIcon = L.divIcon({
            className: 'direction-arrow',
            html: `<div style="transform: rotate(${heading}deg); width: 0; height: 0; border-left: 6px solid transparent; border-right: 6px solid transparent; border-bottom: 12px solid #6366f1;"></div>`,
            iconSize: [12, 12],
            iconAnchor: [6, 6]
        });

        const marker = L.marker([lat, lng], { icon: arrowIcon }).addTo(this.map);
        this.markers.push(marker);
        return marker;
    }

    /**
     * Fit map bounds to show all markers and trajectory
     */
    fitBounds() {
        const items = [...this.markers];

        // Include trajectory line if it exists
        if (this.trajectoryLine) {
            items.push(this.trajectoryLine);
        }

        if (items.length === 0) return;

        const group = L.featureGroup(items);
        this.map.fitBounds(group.getBounds(), { padding: [30, 30] });
    }

    /**
     * Dispose of the map
     */
    dispose() {
        if (this.map) {
            this.map.remove();
            this.map = null;
        }
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MapView;
}
