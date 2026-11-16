import { PangolinApiClient } from "../client.js";
export declare function handleListAIKeys(client: PangolinApiClient): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
export declare function handleCreateAIKey(client: PangolinApiClient, args: any): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
