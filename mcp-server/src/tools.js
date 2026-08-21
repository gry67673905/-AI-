import { z } from 'zod'
import { createExternalMcpServer } from 'smart-gov-mcp-server'

const optionalShortText = (description) => z.string().trim().max(100).optional().describe(description)

export function createSmartGovMcpServer(govApiClient) {
  if (!govApiClient) throw new TypeError('govApiClient is required')

  return createExternalMcpServer({
    name: 'smart-gov-http-tools',
    version: '0.1.0',
    tools: [
      {
        name: 'search_services',
        description: '按关键词和分类搜索政务服务事项；结果是明确标记的演示数据。',
        inputSchema: {
          keyword: optionalShortText('事项名称、编码或办理关键词'),
          category: optionalShortText('事项分类，例如社会保障、公安户政')
        },
        async handler({ keyword = '', category = '' }) {
          return govApiClient.searchServices({ keyword, category })
        }
      },
      {
        name: 'get_service_details',
        description: '获取指定演示政务事项的办理条件、流程、材料和注意事项。',
        inputSchema: {
          id: z.number().int().positive().describe('事项 ID')
        },
        async handler({ id }) {
          return govApiClient.getServiceDetails(id)
        }
      },
      {
        name: 'get_material_checklist',
        description: '获取指定演示政务事项的材料清单，并区分必需和可选材料。',
        inputSchema: {
          itemId: z.number().int().positive().describe('事项 ID')
        },
        async handler({ itemId }) {
          return govApiClient.getMaterialChecklist(itemId)
        }
      }
    ]
  })
}
