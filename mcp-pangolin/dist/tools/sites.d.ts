import { PangolinApiClient } from "../client.js";
export declare function handleListSites(client: PangolinApiClient): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleGetSite(client: PangolinApiClient, args: {
    id: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleCreateSite(client: PangolinApiClient, args: {
    name: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleDeleteSite(client: PangolinApiClient, args: {
    id: string;
}): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
