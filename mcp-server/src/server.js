import { createApp } from './app.js'

const port = Number(process.env.PORT ?? 3000)
const host = process.env.HOST ?? '0.0.0.0'
const { app, closeSessions } = createApp({
  internalToken: process.env.MCP_INTERNAL_TOKEN,
  govApiBaseUrl: process.env.GOV_API_BASE_URL ?? 'http://mock-gov-api:8080',
  govApiToken: process.env.GOV_API_TOKEN,
  sessionTtlMs: Number(process.env.MCP_SESSION_TTL_MS ?? 15 * 60 * 1000),
  maxSessions: Number(process.env.MCP_MAX_SESSIONS ?? 128)
})

const httpServer = app.listen(port, host, () => {
  console.error(`mcp-server listening on ${host}:${port}`)
})

let stopping = false
async function shutdown(signal) {
  if (stopping) return
  stopping = true
  console.error(`mcp-server received ${signal}; shutting down`)
  await closeSessions()
  httpServer.close((error) => {
    if (error) {
      console.error('mcp-server shutdown failed', { name: error.name })
      process.exitCode = 1
    }
  })
}

process.once('SIGTERM', () => void shutdown('SIGTERM'))
process.once('SIGINT', () => void shutdown('SIGINT'))
