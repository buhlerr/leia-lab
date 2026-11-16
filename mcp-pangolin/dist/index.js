#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import dotenv from "dotenv";
import { PangolinApiClient } from "./client.js";
import { CreateResourceSchema, UpdateResourceSchema, ToggleMaintenanceSchema, CreateSiteSchema, CreateAIKeySchema } from "./types.js";
import { handleListResources, handleGetResource, handleCreateResource, handleUpdateResource, handleDeleteResource, handleToggleMaintenance } from "./tools/resources.js";
import { handleListSites, handleGetSite, handleCreateSite, handleDeleteSite } from "./tools/sites.js";
import { handleGetHealthStatus } from "./tools/health.js";
import { handleListAIKeys, handleCreateAIKey } from "./tools/ai_gateway.js";
dotenv.config();
const endpoint = process.env.PANGOLIN_ENDPOINT || "http://localhost:3000";
const apiKey = process.env.PANGOLIN_API_KEY || "";
const client = new PangolinApiClient(endpoint, apiKey);
const server = new McpServer({
    name: "mcp-pangolin",
    version: "1.0.0"
});
// --- Resource Tools ---
server.tool("pangolin_list_resources", "List all configured proxy resources, subdomains, targets, and statuses in Pangolin", {}, async () => handleListResources(client));
server.tool("pangolin_get_resource", "Get configuration and routing details for a specific resource by ID", { id: z.string().describe("Resource ID") }, async (args) => handleGetResource(client, args));
server.tool("pangolin_create_resource", "Create a new reverse proxy resource/route (e.g. Proxmox, OpenWrt, Arcane) in Pangolin", CreateResourceSchema.shape, async (args) => handleCreateResource(client, args));
server.tool("pangolin_update_resource", "Update target, name, site connector, or settings for an existing Pangolin resource", UpdateResourceSchema.shape, async (args) => handleUpdateResource(client, args));
server.tool("pangolin_delete_resource", "Delete a resource route from Pangolin", { id: z.string().describe("Resource ID to delete") }, async (args) => handleDeleteResource(client, args));
server.tool("pangolin_toggle_maintenance", "Enable or disable the friendly maintenance page for a specific resource (useful during host reboots/updates)", ToggleMaintenanceSchema.shape, async (args) => handleToggleMaintenance(client, args));
// --- Site Tools ---
server.tool("pangolin_list_sites", "List all registered Newt Site connectors and their live connection status (Online/Offline)", {}, async () => handleListSites(client));
server.tool("pangolin_get_site", "Get details of a specific site connector by ID", { id: z.string().describe("Site connector ID") }, async (args) => handleGetSite(client, args));
server.tool("pangolin_create_site", "Create a new site connector and generate a pairing token for Newt", CreateSiteSchema.shape, async (args) => handleCreateSite(client, args));
server.tool("pangolin_delete_site", "Remove a site connector from Pangolin", { id: z.string().describe("Site connector ID to delete") }, async (args) => handleDeleteSite(client, args));
// --- Health Status Tools ---
server.tool("pangolin_get_health_status", "Query live health check statuses and uptime for all monitored resources", {}, async () => handleGetHealthStatus(client));
// --- AI Gateway Tools ---
server.tool("pangolin_list_ai_virtual_keys", "List all virtual keys, rate limits, and budget spend in Pangolin AI Gateway", {}, async () => handleListAIKeys(client));
server.tool("pangolin_create_ai_gateway_key", "Create a new virtual key with custom monthly budget and allowed LLM models in AI Gateway", CreateAIKeySchema.shape, async (args) => handleCreateAIKey(client, args));
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("Pangolin MCP Server running on stdio");
}
main().catch((error) => {
    console.error("Fatal error in MCP Pangolin server:", error);
    process.exit(1);
});
