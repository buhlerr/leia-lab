# 🛡️ MCP Server para Pangolin (SASE & ZTNA)

Servidor Model Context Protocol (MCP) que permite a agentes de IA (Antigravity, Claude Desktop, Cursor) gerenciar recursos, rotas de proxy reverso, status de conectores Newt, health checks e AI Gateway na plataforma **Pangolin**.

---

## 🛠️ Ferramentas Disponíveis

| Ferramenta | Descrição |
| :--- | :--- |
| `pangolin_list_resources` | Lista todos os recursos, subdomínios e targets cadastrados |
| `pangolin_get_resource` | Obtém detalhes completos de uma rota de proxy por ID |
| `pangolin_create_resource` | Cadastra nova rota (ex: Proxmox `192.168.0.9:8006`, OpenWrt `192.168.0.1`) |
| `pangolin_update_resource` | Modifica parâmetros de uma rota existente |
| `pangolin_delete_resource` | Remove uma rota do Pangolin |
| `pangolin_toggle_maintenance` | Ativa/desativa a página de manutenção de um recurso |
| `pangolin_list_sites` | Lista os conectores Newt e status da conexão (Online/Offline) |
| `pangolin_get_site` | Detalhes de um conector de site específico |
| `pangolin_create_site` | Cria um novo conector de site e retorna o token de pareamento |
| `pangolin_delete_site` | Remove um conector de site |
| `pangolin_get_health_status` | Consulta status de saúde ativo e uptime dos targets locais |
| `pangolin_list_ai_virtual_keys` | Lista chaves virtuais e limites no AI Gateway |
| `pangolin_create_ai_gateway_key` | Cria chave virtual com orçamento e restrições de modelos |

---

## 🚀 Instalação e Compilação

```bash
cd mcp-pangolin
npm install
npm run build
```

---

## ⚙️ Configuração no Antigravity / Claude Desktop

Adicione ao seu arquivo de configuração MCP (`mcp_config.json`):

```json
{
  "mcpServers": {
    "pangolin": {
      "command": "node",
      "args": [
        "C:\\Users\\Vitor\\Documents\\Desenvolvimentos\\homelab\\mcp-pangolin\\dist\\index.js"
      ],
      "env": {
        "PANGOLIN_ENDPOINT": "https://pangolin.seudominio.com",
        "PANGOLIN_API_KEY": "SEU_TOKEN_ADMIN_AQUI"
      }
    }
  }
}
```
