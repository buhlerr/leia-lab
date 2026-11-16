import axios from "axios";
export class PangolinApiClient {
    client;
    endpoint;
    orgId = null;
    constructor(endpoint, apiKey) {
        this.endpoint = endpoint.replace(/\/+$/, "");
        const baseURL = this.endpoint.endsWith("/v1") ? this.endpoint : `${this.endpoint}/v1`;
        this.client = axios.create({
            baseURL,
            headers: {
                "Authorization": `Bearer ${apiKey}`,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout: 10000
        });
    }
    async getOrgId() {
        if (this.orgId)
            return this.orgId;
        const res = await this.client.get("/orgs");
        const orgs = res.data?.data?.orgs || [];
        if (orgs.length > 0 && orgs[0].orgId) {
            this.orgId = orgs[0].orgId;
            return this.orgId;
        }
        throw new Error("No organization found in Pangolin account.");
    }
    // --- Domains ---
    async listDomains() {
        const orgId = await this.getOrgId();
        const res = await this.client.get(`/org/${orgId}/domains`);
        return res.data?.data?.domains || [];
    }
    // --- Resources ---
    async listResources() {
        const orgId = await this.getOrgId();
        const res = await this.client.get(`/org/${orgId}/resources`);
        return res.data?.data?.resources || [];
    }
    async getResource(id) {
        const res = await this.client.get(`/resource/${id}`);
        return res.data?.data || res.data;
    }
    async createResource(payload) {
        const orgId = await this.getOrgId();
        // 1. Resolve domainId if domain string was passed
        let domainId = payload.domainId;
        if (!domainId && payload.domain) {
            const domains = await this.listDomains();
            const match = domains.find((d) => d.baseDomain === payload.domain || d.domainId === payload.domain);
            domainId = match ? match.domainId : "domain1";
        }
        // 2. Create resource
        const resourcePayload = {
            name: payload.name,
            subdomain: payload.subdomain,
            domainId: domainId || "domain1",
            mode: payload.mode || "http"
        };
        const res = await this.client.put(`/org/${orgId}/resource`, resourcePayload);
        const created = res.data?.data;
        const resourceId = created?.resourceId;
        // 3. Attach target if specified
        if (resourceId && (payload.target || payload.ip)) {
            let ip = payload.ip;
            let port = payload.port;
            let method = payload.protocol || payload.method || "http";
            if (payload.target) {
                try {
                    const url = new URL(payload.target.startsWith("http") ? payload.target : `http://${payload.target}`);
                    ip = url.hostname;
                    port = url.port ? parseInt(url.port, 10) : (url.protocol === "https:" ? 443 : 80);
                    method = url.protocol.replace(":", "");
                }
                catch {
                    const parts = payload.target.replace(/^https?:\/\//, "").split(":");
                    ip = parts[0];
                    port = parts[1] ? parseInt(parts[1], 10) : 80;
                }
            }
            let siteId = payload.site_id ? parseInt(payload.site_id, 10) : payload.siteId;
            if (!siteId) {
                const sites = await this.listSites();
                if (sites.length > 0) {
                    siteId = sites[0].siteId || sites[0].id;
                }
            }
            if (siteId && ip && port) {
                const targetRes = await this.client.put(`/resource/${resourceId}/target`, {
                    siteId,
                    ip,
                    port,
                    method,
                    mode: payload.mode || "http"
                });
                created.target = targetRes.data?.data;
            }
        }
        return created;
    }
    async updateResource(id, payload) {
        const resourcePayload = {};
        if (payload.name)
            resourcePayload.name = payload.name;
        if (payload.maintenance_mode !== undefined) {
            resourcePayload.maintenanceModeEnabled = payload.maintenance_mode;
            resourcePayload.maintenanceModeType = "forced";
        }
        let updatedResource = null;
        if (Object.keys(resourcePayload).length > 0) {
            const res = await this.client.post(`/resource/${id}`, resourcePayload);
            updatedResource = res.data?.data || res.data;
        }
        if (payload.target || payload.protocol || payload.method || payload.site_id) {
            const orgId = await this.getOrgId();
            const resList = await this.client.get(`/org/${orgId}/resources`);
            const allResources = resList.data?.data?.resources || [];
            const resource = allResources.find((r) => String(r.resourceId) === String(id));
            const targetObj = resource?.targets?.[0];
            if (targetObj) {
                let ip = targetObj.ip;
                let port = targetObj.port;
                let method = payload.protocol || payload.method || targetObj.method || "http";
                let siteId = payload.site_id ? parseInt(payload.site_id, 10) : targetObj.siteId;
                if (payload.target) {
                    try {
                        const url = new URL(payload.target.startsWith("http") ? payload.target : `http://${payload.target}`);
                        ip = url.hostname;
                        port = url.port ? parseInt(url.port, 10) : (url.protocol === "https:" ? 443 : 80);
                        if (!payload.protocol && !payload.method) {
                            method = url.protocol.replace(":", "");
                        }
                    }
                    catch {
                        const parts = payload.target.replace(/^https?:\/\//, "").split(":");
                        ip = parts[0];
                        port = parts[1] ? parseInt(parts[1], 10) : targetObj.port;
                    }
                }
                await this.client.post(`/target/${targetObj.targetId}`, {
                    siteId,
                    ip,
                    port,
                    method
                });
            }
        }
        return updatedResource || await this.getResource(id);
    }
    async deleteResource(id) {
        const res = await this.client.delete(`/resource/${id}`);
        return res.data || { success: true };
    }
    async toggleMaintenance(id, enabled) {
        const res = await this.client.post(`/resource/${id}`, {
            maintenanceModeEnabled: enabled,
            maintenanceModeType: "forced"
        });
        return res.data?.data || res.data;
    }
    // --- Sites (Newt Connectors) ---
    async listSites() {
        const orgId = await this.getOrgId();
        const res = await this.client.get(`/org/${orgId}/sites`);
        return res.data?.data?.sites || [];
    }
    async getSite(id) {
        const res = await this.client.get(`/site/${id}`);
        return res.data?.data || res.data;
    }
    async createSite(name) {
        const orgId = await this.getOrgId();
        const res = await this.client.put(`/org/${orgId}/site`, {
            name,
            type: "newt"
        });
        return res.data?.data || res.data;
    }
    async deleteSite(id) {
        const res = await this.client.delete(`/site/${id}`);
        return res.data || { success: true };
    }
    // --- Health Checks ---
    async getHealthChecks() {
        const orgId = await this.getOrgId();
        const res = await this.client.get(`/org/${orgId}/health-checks`);
        return res.data?.data || res.data || [];
    }
    // --- AI Gateway ---
    async listAIVirtualKeys() {
        const orgId = await this.getOrgId();
        const res = await this.client.get(`/org/${orgId}/virtual-api-keys`);
        return res.data?.data?.virtualApiKeys || [];
    }
    async createAIVirtualKey(payload) {
        const orgId = await this.getOrgId();
        const res = await this.client.put(`/org/${orgId}/virtual-api-key`, {
            name: payload.name,
            description: payload.description,
            allResources: true
        });
        return res.data?.data || res.data;
    }
}
