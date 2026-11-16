import { z } from "zod";

export interface PangolinConfig {
  endpoint: string;
  apiKey: string;
}

export interface PangolinResource {
  id: string;
  name: string;
  domain: string;
  subdomain: string;
  target: string;
  protocol?: "http" | "https" | "tcp" | "udp";
  site_id?: string;
  site_name?: string;
  insecure_skip_verify?: boolean;
  maintenance_mode?: boolean;
  health_check?: {
    enabled: boolean;
    path?: string;
    interval_seconds?: number;
    status?: "healthy" | "unhealthy" | "unknown";
    last_check?: string;
  };
  created_at?: string;
  updated_at?: string;
}

export interface PangolinSite {
  id: string;
  name: string;
  status: "connected" | "disconnected" | "pending";
  last_seen?: string;
  remote_ip?: string;
  token?: string;
  resources_count?: number;
  created_at?: string;
}

export interface PangolinAIVirtualKey {
  id: string;
  name: string;
  key_prefix: string;
  budget_limit?: number;
  budget_spent?: number;
  allowed_models?: string[];
  rate_limit_rpm?: number;
  enabled: boolean;
  created_at?: string;
}

export const CreateResourceSchema = z.object({
  name: z.string().describe("Human-readable name for the resource (e.g. 'Proxmox VE')"),
  domain: z.string().describe("Base domain (e.g. 'meudominio.com')"),
  subdomain: z.string().describe("Subdomain prefix (e.g. 'pve' for 'pve.meudominio.com')"),
  target: z.string().describe("Internal destination URL/address (e.g. 'https://192.168.0.9:8006' or 'http://192.168.0.1:80')"),
  protocol: z.enum(["http", "https", "tcp", "udp"]).default("https").describe("Protocol used by target"),
  site_id: z.string().optional().describe("ID of the Newt Site connector routing this resource"),
  insecure_skip_verify: z.boolean().default(true).describe("Whether to ignore self-signed TLS certificates on the target"),
  enable_health_check: z.boolean().default(true).describe("Enable proactive health checks for this resource"),
  health_check_path: z.string().default("/").describe("Path to query for HTTP health checks")
});

export const UpdateResourceSchema = z.object({
  id: z.string().describe("ID of the resource to update"),
  name: z.string().optional().describe("Updated name"),
  target: z.string().optional().describe("Updated target URL/IP"),
  protocol: z.enum(["http", "https", "tcp", "udp"]).optional().describe("Protocol used by target (e.g. 'https' or 'http')"),
  site_id: z.string().optional().describe("Updated site connector ID"),
  insecure_skip_verify: z.boolean().optional().describe("Update TLS verification bypass"),
  maintenance_mode: z.boolean().optional().describe("Toggle maintenance page"),
  enable_health_check: z.boolean().optional().describe("Toggle health checks")
});

export const ToggleMaintenanceSchema = z.object({
  id: z.string().describe("ID of the resource"),
  enabled: z.boolean().describe("true to show maintenance page, false to resume normal routing")
});

export const CreateSiteSchema = z.object({
  name: z.string().describe("Name of the site connector (e.g. 'homelab-dell3020m')")
});

export const CreateAIKeySchema = z.object({
  name: z.string().describe("Descriptive name for the AI Gateway virtual key"),
  budget_limit: z.number().optional().describe("Monthly budget limit in USD (e.g. 10.00)"),
  allowed_models: z.array(z.string()).optional().describe("List of allowed model IDs (e.g. ['gemini-2.5-flash', 'claude-3-5-sonnet'])"),
  rate_limit_rpm: z.number().optional().describe("Requests per minute rate limit")
});
