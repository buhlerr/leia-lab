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
export declare const CreateResourceSchema: z.ZodObject<{
    name: z.ZodString;
    domain: z.ZodString;
    subdomain: z.ZodString;
    target: z.ZodString;
    protocol: z.ZodDefault<z.ZodEnum<["http", "https", "tcp", "udp"]>>;
    site_id: z.ZodOptional<z.ZodString>;
    insecure_skip_verify: z.ZodDefault<z.ZodBoolean>;
    enable_health_check: z.ZodDefault<z.ZodBoolean>;
    health_check_path: z.ZodDefault<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    name: string;
    domain: string;
    subdomain: string;
    target: string;
    protocol: "http" | "https" | "tcp" | "udp";
    insecure_skip_verify: boolean;
    enable_health_check: boolean;
    health_check_path: string;
    site_id?: string | undefined;
}, {
    name: string;
    domain: string;
    subdomain: string;
    target: string;
    protocol?: "http" | "https" | "tcp" | "udp" | undefined;
    site_id?: string | undefined;
    insecure_skip_verify?: boolean | undefined;
    enable_health_check?: boolean | undefined;
    health_check_path?: string | undefined;
}>;
export declare const UpdateResourceSchema: z.ZodObject<{
    id: z.ZodString;
    name: z.ZodOptional<z.ZodString>;
    target: z.ZodOptional<z.ZodString>;
    protocol: z.ZodOptional<z.ZodEnum<["http", "https", "tcp", "udp"]>>;
    site_id: z.ZodOptional<z.ZodString>;
    insecure_skip_verify: z.ZodOptional<z.ZodBoolean>;
    maintenance_mode: z.ZodOptional<z.ZodBoolean>;
    enable_health_check: z.ZodOptional<z.ZodBoolean>;
}, "strip", z.ZodTypeAny, {
    id: string;
    name?: string | undefined;
    target?: string | undefined;
    protocol?: "http" | "https" | "tcp" | "udp" | undefined;
    site_id?: string | undefined;
    insecure_skip_verify?: boolean | undefined;
    enable_health_check?: boolean | undefined;
    maintenance_mode?: boolean | undefined;
}, {
    id: string;
    name?: string | undefined;
    target?: string | undefined;
    protocol?: "http" | "https" | "tcp" | "udp" | undefined;
    site_id?: string | undefined;
    insecure_skip_verify?: boolean | undefined;
    enable_health_check?: boolean | undefined;
    maintenance_mode?: boolean | undefined;
}>;
export declare const ToggleMaintenanceSchema: z.ZodObject<{
    id: z.ZodString;
    enabled: z.ZodBoolean;
}, "strip", z.ZodTypeAny, {
    id: string;
    enabled: boolean;
}, {
    id: string;
    enabled: boolean;
}>;
export declare const CreateSiteSchema: z.ZodObject<{
    name: z.ZodString;
}, "strip", z.ZodTypeAny, {
    name: string;
}, {
    name: string;
}>;
export declare const CreateAIKeySchema: z.ZodObject<{
    name: z.ZodString;
    budget_limit: z.ZodOptional<z.ZodNumber>;
    allowed_models: z.ZodOptional<z.ZodArray<z.ZodString, "many">>;
    rate_limit_rpm: z.ZodOptional<z.ZodNumber>;
}, "strip", z.ZodTypeAny, {
    name: string;
    budget_limit?: number | undefined;
    allowed_models?: string[] | undefined;
    rate_limit_rpm?: number | undefined;
}, {
    name: string;
    budget_limit?: number | undefined;
    allowed_models?: string[] | undefined;
    rate_limit_rpm?: number | undefined;
}>;
