export async function handleGetHealthStatus(client) {
    const healthData = await client.getHealthChecks();
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify(healthData, null, 2)
            }
        ]
    };
}
