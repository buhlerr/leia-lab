import { PangolinApiClient } from "../client.js";
export declare function handleGetHealthStatus(client: PangolinApiClient): Promise<{
    content: {
        type: "text";
        text: string;
    }[];
}>;
