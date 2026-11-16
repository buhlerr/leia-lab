import { PangolinApiClient } from "../client.js";
export declare function handleListResources(client: PangolinApiClient): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleGetResource(client: PangolinApiClient, args: {
    id: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleCreateResource(client: PangolinApiClient, args: any): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleUpdateResource(client: PangolinApiClient, args: any): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleDeleteResource(client: PangolinApiClient, args: {
    id: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleToggleMaintenance(client: PangolinApiClient, args: {
    id: string;
    enabled: boolean;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
