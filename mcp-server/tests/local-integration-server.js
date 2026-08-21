import http from 'node:http'
import { createApp } from '../src/app.js'

const created = createApp({
  internalToken: 'integration-mcp-token',
  govApiBaseUrl: 'http://127.0.0.1:18080',
  govApiToken: 'integration-gov-token'
})
const server = http.createServer(created.app)

server.listen(13001, '127.0.0.1', () => {
  process.stderr.write('integration MCP listening on 127.0.0.1:13001\n')
})

async function shutdown() {
  await created.closeSessions()
  server.close(() => process.exit(0))
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

