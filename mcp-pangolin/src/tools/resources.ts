import { PangolinApiClient } from "../client.js";

export async function handleListResources(client: PangolinApiClient) {
  const resources = await client.listResources();
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(resources, null, 2)
      }
    ]
  };
}

export async function handleGetResource(client: PangolinApiClient, args: { id: string }) {
  const resource = await client.getResource(args.id);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(resource, null, 2)
      }
    ]
  };
}

export async function handleCreateResource(client: PangolinApiClient, args: any) {
  const result = await client.createResource(args);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(
          {
            message: `Resource '${args.name}' created successfully.`,
            resource: result
          },
          null,
          2
        )
      }
    ]
  };
}

export async function handleUpdateResource(client: PangolinApiClient, args: any) {
  const { id, ...payload } = args;
  const result = await client.updateResource(id, payload);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(
          {
            message: `Resource ID '${id}' updated successfully.`,
            resource: result
          },
          null,
          2
        )
      }
    ]
  };
}

export async function handleDeleteResource(client: PangolinApiClient, args: { id: string }) {
  const result = await client.deleteResource(args.id);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(
          {
            message: `Resource ID '${args.id}' deleted successfully.`,
            details: result
          },
          null,
          2
        )
      }
    ]
  };
}

export async function handleToggleMaintenance(client: PangolinApiClient, args: { id: string; enabled: boolean }) {
  const result = await client.toggleMaintenance(args.id, args.enabled);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(
          {
            message: `Maintenance mode for Resource ID '${args.id}' set to: ${args.enabled ? "ENABLED" : "DISABLED"}.`,
            resource: result
          },
          null,
          2
        )
      }
    ]
  };
}
