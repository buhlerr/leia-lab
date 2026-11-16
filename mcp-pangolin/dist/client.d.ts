export declare class PangolinApiClient {
    private client;
    private endpoint;
    private orgId;
    constructor(endpoint: string, apiKey: string);
    getOrgId(): Promise<string>;
    listDomains(): Promise<any[]>;
    listResources(): Promise<any[]>;
    getResource(id: string | number): Promise<any>;
    createResource(payload: any): Promise<any>;
    updateResource(id: string | number, payload: any): Promise<any>;
    deleteResource(id: string | number): Promise<{
        success: boolean;
        message?: string;
    }>;
    toggleMaintenance(id: string | number, enabled: boolean): Promise<any>;
    listSites(): Promise<any[]>;
    getSite(id: string | number): Promise<any>;
    createSite(name: string): Promise<any>;
    deleteSite(id: string | number): Promise<{
        success: boolean;
    }>;
    getHealthChecks(): Promise<any[]>;
    listAIVirtualKeys(): Promise<any[]>;
    createAIVirtualKey(payload: any): Promise<any>;
}
