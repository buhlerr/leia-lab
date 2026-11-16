export async function handleListResources(client) {
    const resources = await client.listResources();
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify(resources, null, 2)
            }
        ]
    };
}
export async function handleGetResource(client, args) {
    const resource = await client.getResource(args.id);
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify(resource, null, 2)
            }
        ]
    };
}
export async function handleCreateResource(client, args) {
    const result = await client.createResource(args);
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify({
                    message: `Resource '${args.name}' created successfully.`,
                    resource: result
                }, null, 2)
            }
        ]
    };
}
export async function handleUpdateResource(client, args) {
    const { id, ...payload } = args;
    const result = await client.updateResource(id, payload);
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify({
                    message: `Resource ID '${id}' updated successfully.`,
                    resource: result
                }, null, 2)
            }
        ]
    };
}
export async function handleDeleteResource(client, args) {
    const result = await client.deleteResource(args.id);
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify({
                    message: `Resource ID '${args.id}' deleted successfully.`,
                    details: result
                }, null, 2)
            }
        ]
    };
}
export async function handleToggleMaintenance(client, args) {
    const result = await client.toggleMaintenance(args.id, args.enabled);
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify({
                    message: `Maintenance mode for Resource ID '${args.id}' set to: ${args.enabled ? "ENABLED" : "DISABLED"}.`,
                    resource: result
                }, null, 2)
            }
        ]
    };
}
