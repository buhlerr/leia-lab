export async function handleListAIKeys(client) {
    const keys = await client.listAIVirtualKeys();
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify(keys, null, 2)
            }
        ]
    };
}
export async function handleCreateAIKey(client, args) {
    const result = await client.createAIVirtualKey(args);
    return {
        content: [
            {
                type: "text",
                text: JSON.stringify({
                    message: `AI Gateway Virtual Key '${args.name}' created successfully.`,
                    virtual_key: result,
                    note: "Make sure to copy the full API key token now as it will not be shown again."
                }, null, 2)
            }
        ]
    };
}
