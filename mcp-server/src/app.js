import { randomUUID } from 'node:crypto'
import express from 'express'
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js'
import { isInitializeRequest } from '@modelcontextprotocol/sdk/types.js'
import { readBearerToken, tokensMatch } from './auth.js'
import { GovApiClient } from './gov-api-client.js'
import { createSmartGovMcpServer } from './tools.js'

function jsonRpcError(response, status, code, message) {
  response.status(status).json({
    jsonrpc: '2.0',
    error: { code, message },
    id: null
  })
}

function sessionIdFrom(request) {
  const value = request.get('mcp-session-id')
  return typeof value === 'string' && value ? value : null
}

export function createApp({
  internalToken,
  govApiBaseUrl,
  govApiToken,
  fetchImpl = globalThis.fetch,
  logger = console
} = {}) {
  if (!internalToken) throw new Error('MCP_INTERNAL_TOKEN is required')
  const govApiClient = new GovApiClient({
    baseUrl: govApiBaseUrl,
    token: govApiToken,
    fetchImpl
  })
  const sessions = new Map()
  const app = express()
  app.disable('x-powered-by')
  app.use(express.json({ limit: '256kb' }))

  app.get('/health', (_request, response) => {
    response.json({ status: 'ok', service: 'mcp-server', transport: 'streamable-http' })
  })

  app.use('/mcp', (request, response, next) => {
    if (!tokensMatch(internalToken, readBearerToken(request.get('authorization')))) {
      return jsonRpcError(response, 401, -32001, 'Unauthorized')
    }
    next()
  })

  app.post('/mcp', async (request, response) => {
    const requestedSessionId = sessionIdFrom(request)
    let entry = requestedSessionId ? sessions.get(requestedSessionId) : undefined

    if (!entry && !requestedSessionId && isInitializeRequest(request.body)) {
      const server = createSmartGovMcpServer(govApiClient)
      let transport
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: randomUUID,
        enableJsonResponse: true,
        onsessioninitialized(sessionId) {
          sessions.set(sessionId, { server, transport })
        }
      })
      transport.onclose = () => {
        if (transport.sessionId) sessions.delete(transport.sessionId)
      }
      entry = { server, transport }
      await server.connect(transport)
    } else if (!entry) {
      return jsonRpcError(response, 400, -32000, 'Bad Request: missing or invalid MCP session')
    }

    try {
      await entry.transport.handleRequest(request, response, request.body)
    } catch (error) {
      logger.error?.('MCP request failed', { name: error?.name })
      if (!response.headersSent) {
        jsonRpcError(response, 500, -32603, 'Internal server error')
      }
    }
  })

  const handleEstablishedSession = async (request, response) => {
    const sessionId = sessionIdFrom(request)
    const entry = sessionId ? sessions.get(sessionId) : undefined
    if (!entry) return jsonRpcError(response, 400, -32000, 'Bad Request: invalid MCP session')
    try {
      await entry.transport.handleRequest(request, response)
    } catch (error) {
      logger.error?.('MCP session request failed', { name: error?.name })
      if (!response.headersSent) {
        jsonRpcError(response, 500, -32603, 'Internal server error')
      }
    }
  }

  app.get('/mcp', handleEstablishedSession)
  app.delete('/mcp', handleEstablishedSession)

  app.use((request, response) => {
    response.status(404).json({ error: { code: 'not_found', message: '接口不存在。' } })
  })

  async function closeSessions() {
    const current = [...sessions.values()]
    sessions.clear()
    await Promise.allSettled(current.map(async ({ server, transport }) => {
      await transport.close()
      await server.close()
    }))
  }

  return { app, closeSessions, sessions }
}
