/**
 * API Client for VLN Benchmark Platform
 * Handles all HTTP API calls to the backend
 */

const apiClient = {
    baseUrl: '/api',

    /**
     * Make an API request
     */
    async request(endpoint, options = {}) {
        const url = this.baseUrl + endpoint;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };

        if (options.body && typeof options.body === 'object') {
            config.body = JSON.stringify(options.body);
        }

        const response = await fetch(url, config);

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return response.json();
    },

    // === Session Management ===

    /**
     * Create a new evaluation session
     * @param {string} agentId - Agent or player identifier
     * @param {string} taskId - Task identifier
     * @param {string} mode - 'agent' or 'human'
     */
    async createSession(agentId, taskId, mode = 'agent') {
        return this.request('/session/create', {
            method: 'POST',
            body: { agent_id: agentId, task_id: taskId, mode }
        });
    },

    /**
     * Get current session state
     * @param {string} sessionId - Session identifier
     */
    async getSessionState(sessionId) {
        return this.request(`/session/${sessionId}/state`);
    },

    /**
     * Execute an action in a session
     * @param {string} sessionId - Session identifier
     * @param {object} action - Action to execute
     */
    async executeAction(sessionId, action) {
        return this.request(`/session/${sessionId}/action`, {
            method: 'POST',
            body: action
        });
    },

    /**
     * End a session
     * @param {string} sessionId - Session identifier
     */
    async endSession(sessionId) {
        return this.request(`/session/${sessionId}/end`, {
            method: 'POST'
        });
    },

    /**
     * Pause a human evaluation session
     * @param {string} sessionId - Session identifier
     */
    async pauseSession(sessionId) {
        return this.request(`/session/${sessionId}/pause`, {
            method: 'POST'
        });
    },

    /**
     * Resume a paused session
     * @param {string} sessionId - Session identifier
     */
    async resumeSession(sessionId) {
        return this.request(`/session/${sessionId}/resume`, {
            method: 'POST'
        });
    },

    /**
     * Get list of all session logs
     */
    async getSessions() {
        return this.request('/sessions');
    },

    /**
     * Get full log for a session
     * @param {string} sessionId - Session identifier
     */
    async getSessionLog(sessionId) {
        return this.request(`/sessions/${sessionId}/log`);
    },

    // === Task Management ===


    /**
     * Get list of all tasks
     */
    async getTasks() {
        return this.request('/tasks');
    },

    /**
     * Get task details
     * @param {string} taskId - Task identifier
     */
    async getTask(taskId) {
        return this.request(`/tasks/${taskId}`);
    },

    /**
     * Start preloading panoramas for a task
     * @param {string} taskId - Task identifier
     * @param {number} zoomLevel - Optional zoom level
     */
    async preloadTask(taskId, zoomLevel = null) {
        const body = {};
        if (zoomLevel !== null) {
            body.zoom_level = zoomLevel;
        }
        return this.request(`/tasks/${taskId}/preload`, {
            method: 'POST',
            body
        });
    },

    /**
     * Get preload status for a task
     * @param {string} taskId - Task identifier
     */
    async getPreloadStatus(taskId) {
        return this.request(`/tasks/${taskId}/preload/status`);
    },

    // === Player Progress ===

    /**
     * Get player progress
     * @param {string} playerId - Player identifier
     */
    async getPlayerProgress(playerId) {
        return this.request(`/players/${playerId}/progress`);
    }
};

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = apiClient;
}
