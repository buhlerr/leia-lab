import { PangolinApiClient } from "../client.js";

export async function handleListSites(client: PangolinApiClient) {
  const sites = await client.listSites();
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(sites, null, 2)
      }
    ]
  };
}

export async function handleGetSite(client: PangolinApiClient, args: { id: string }) {
  const site = await client.getSite(args.id);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(site, null, 2)
      }
    ]
  };
}

export async function handleCreateSite(client: PangolinApiClient, args: { name: string }) {
  const result = await client.createSite(args.name);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(
          {
            message: `Site connector '${args.name}' created successfully.`,
            site: result,
            instructions: "Use the returned token in your Newt docker-compose.yml or systemd service as SITE_TOKEN."
          },
          null,
          2
        )
      }
    ]
  };
}

export async function handleDeleteSite(client: PangolinApiClient, args: { id: string }) {
  const result = await client.deleteSite(args.id);
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(
          {
            message: `Site connector ID '${args.id}' deleted successfully.`,
            details: result
          },
          null,
          2
        )
      }
    ]
  };
}
