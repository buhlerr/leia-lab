import { PangolinApiClient } from "../client.js";

export async function handleGetHealthStatus(client: PangolinApiClient) {
  const healthData = await client.getHealthChecks();
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(healthData, null, 2)
      }
    ]
  };
}
