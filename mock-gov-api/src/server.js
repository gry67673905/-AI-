import { createApp } from './app.js'

const port = Number(process.env.PORT ?? 8080)
const host = process.env.HOST ?? '0.0.0.0'
const app = createApp({ token: process.env.GOV_API_TOKEN })

const server = app.listen(port, host, () => {
  console.error(`mock-gov-api listening on ${host}:${port}`)
})

function shutdown(signal) {
  console.error(`mock-gov-api received ${signal}; shutting down`)
  server.close((error) => {
    if (error) {
      console.error('mock-gov-api shutdown failed', { name: error.name })
      process.exitCode = 1
    }
  })
}

process.once('SIGTERM', () => shutdown('SIGTERM'))
process.once('SIGINT', () => shutdown('SIGINT'))
