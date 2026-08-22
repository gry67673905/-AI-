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
  logger = console,
  sessionTtlMs = 15 * 60 * 1000,
  maxSessions = 128
} = {}) {
  if (!internalToken) throw new Error('MCP_INTERNAL_TOKEN is required')
  if (!Number.isFinite(sessionTtlMs) || sessionTtlMs <= 0) {
    throw new Error('sessionTtlMs must be a positive number')
  }
  if (!Number.isInteger(maxSessions) || maxSessions <= 0) {
    throw new Error('maxSessions must be a positive integer')
  }
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

  async function disposeSession(sessionId, entry) {
    if (sessions.get(sessionId) !== entry) return
    sessions.delete(sessionId)
    await Promise.allSettled([
      entry.transport.close(),
      entry.server.close()
    ])
  }

  async function sweepExpiredSessions(now = Date.now()) {
    const expired = [...sessions.entries()]
      .filter(([, entry]) => now - entry.lastAccessedAt >= sessionTtlMs)
    await Promise.allSettled(expired.map(([sessionId, entry]) => disposeSession(sessionId, entry)))
  }

  const sweepTimer = setInterval(() => {
    void sweepExpiredSessions().catch((error) => {
      logger.error?.('MCP session cleanup failed', { name: error?.name })
    })
  }, Math.min(sessionTtlMs, 60 * 1000))
  sweepTimer.unref?.()

  app.post('/mcp', async (request, response) => {
    await sweepExpiredSessions()
    const requestedSessionId = sessionIdFrom(request)
    let entry = requestedSessionId ? sessions.get(requestedSessionId) : undefined
    if (entry) entry.lastAccessedAt = Date.now()

    if (!entry && !requestedSessionId && isInitializeRequest(request.body)) {
      if (sessions.size >= maxSessions) {
        return jsonRpcError(response, 503, -32002, 'MCP session capacity reached')
      }
      const server = createSmartGovMcpServer(govApiClient)
      let transport
      const createdEntry = { server, transport: null, lastAccessedAt: Date.now() }
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: randomUUID,
        enableJsonResponse: true,
        onsessioninitialized(sessionId) {
          createdEntry.lastAccessedAt = Date.now()
          sessions.set(sessionId, createdEntry)
        }
      })
      createdEntry.transport = transport
      transport.onclose = () => {
        if (transport.sessionId && sessions.get(transport.sessionId) === createdEntry) {
          sessions.delete(transport.sessionId)
        }
      }
      entry = createdEntry
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
    await sweepExpiredSessions()
    const sessionId = sessionIdFrom(request)
    const entry = sessionId ? sessions.get(sessionId) : undefined
    if (!entry) return jsonRpcError(response, 400, -32000, 'Bad Request: invalid MCP session')
    entry.lastAccessedAt = Date.now()
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
    clearInterval(sweepTimer)
    const current = [...sessions.values()]
    sessions.clear()
    await Promise.allSettled(current.map(async ({ server, transport }) => {
      await transport.close()
      await server.close()
    }))
  }

  return { app, closeSessions, sessions }
}
