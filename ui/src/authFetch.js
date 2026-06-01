// Helper to make authenticated fetch requests
export function createAuthFetch(accessToken) {
    return async function authFetch(url, options = {}) {
        const headers = {
            ...options.headers,
            ...(accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {})
        };

        return fetch(url, {
            ...options,
            headers
        });
    };
}
