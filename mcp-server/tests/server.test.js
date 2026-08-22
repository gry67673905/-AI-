import http from 'node:http'
import assert from 'node:assert/strict'
import { after, before, describe, test } from 'node:test'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { createApp } from '../src/app.js'

const MCP_TOKEN = 'test-mcp-internal-token'
const GOV_TOKEN = 'test-gov-api-token'
let fakeGovServer
let fakeGovBaseUrl
let mcpHttpServer
let mcpBaseUrl
let closeSessions
let sessions
let observedGovAuthorization

function listen(server) {
  return new Promise((resolve, reject) => {
    server.listen(0, '127.0.0.1', resolve)
    server.once('error', reject)
  })
}

function close(server) {
  return new Promise((resolve) => server.close(resolve))
}

before(async () => {
  fakeGovServer = http.createServer((request, response) => {
    observedGovAuthorization = request.headers.authorization
    response.setHeader('content-type', 'application/json')
    if (request.headers.authorization !== `Bearer ${GOV_TOKEN}`) {
      response.statusCode = 401
      return response.end(JSON.stringify({ error: { code: 'unauthorized' }, is_demo: true }))
    }

    const url = new URL(request.url, 'http://mock.local')
    if (url.pathname === '/services') {
      return response.end(JSON.stringify({
        items: [{ id: 1001, name: '社会保障卡申领', is_demo: true }],
        total: 1,
        is_demo: true
      }))
    }
    if (url.pathname === '/services/1001') {
      return response.end(JSON.stringify({
        service: { id: 1001, name: '社会保障卡申领', is_demo: true },
        is_demo: true
      }))
    }
    if (url.pathname === '/services/1001/materials') {
      return response.end(JSON.stringify({
        item_id: 1001,
        required: [{ name: '有效身份证件', required: true }],
        conditional: [],
        optional: [],
        is_demo: true
      }))
    }
    if (url.pathname === '/services/1001/process') {
      return response.end(JSON.stringify({
        item_id: 1001,
        steps: [{ order: 1, code: 'SUBMIT', name: '提交申请' }],
        appointment: { supported: true, required: false },
        fee: { required: false, amount_yuan: 0 },
        delivery: { options: ['WINDOW_PICKUP', 'DEMO_MAIL'] },
        is_demo: true
      }))
    }
    if (url.pathname === '/services/1001/windows') {
      const windowId = url.searchParams.get('window_id')
      return response.end(JSON.stringify({
        item_id: 1001,
        windows: [{
          id: windowId || 'HRSS-CENTER-01',
          name: '演示市民服务中心人社窗口',
          coordinate_type: 'DEMO_GCJ02',
          is_demo: true
        }],
        total: 1,
        is_demo: true
      }))
    }
    response.statusCode = 404
    response.end(JSON.stringify({ error: { code: 'not_found' }, is_demo: true }))
  })
  await listen(fakeGovServer)
  fakeGovBaseUrl = `http://127.0.0.1:${fakeGovServer.address().port}`

  const created = createApp({
    internalToken: MCP_TOKEN,
    govApiBaseUrl: fakeGovBaseUrl,
    govApiToken: GOV_TOKEN,
    logger: { error() {} }
  })
  closeSessions = created.closeSessions
  sessions = created.sessions
  mcpHttpServer = http.createServer(created.app)
  await listen(mcpHttpServer)
  mcpBaseUrl = `http://127.0.0.1:${mcpHttpServer.address().port}`
})

after(async () => {
  await closeSessions?.()
  if (mcpHttpServer) await close(mcpHttpServer)
  if (fakeGovServer) await close(fakeGovServer)
})

describe('MCP Streamable HTTP server', () => {
  test('health is public and does not expose configuration or secrets', async () => {
    const response = await fetch(`${mcpBaseUrl}/health`)
    assert.equal(response.status, 200)
    const text = await response.text()
    assert.equal(JSON.parse(text).transport, 'streamable-http')
    assert.equal(text.includes(MCP_TOKEN), false)
    assert.equal(text.includes(GOV_TOKEN), false)
    assert.equal(text.includes(fakeGovBaseUrl), false)
  })

  test('rejects an unauthenticated MCP request', async () => {
    const response = await fetch(`${mcpBaseUrl}/mcp`)
    assert.equal(response.status, 401)
    assert.equal((await response.json()).error.code, -32001)
  })

  test('lists and calls exactly the five read-only tools with one result wrapper', async () => {
    const client = new Client({ name: 'mcp-test-client', version: '0.1.0' })
    const transport = new StreamableHTTPClientTransport(new URL(`${mcpBaseUrl}/mcp`), {
      requestInit: { headers: { authorization: `Bearer ${MCP_TOKEN}` } }
    })

    try {
      await client.connect(transport)
      const listed = await client.listTools()
      assert.deepEqual(
        listed.tools.map((tool) => tool.name).sort(),
        [
          'get_material_checklist',
          'get_process_navigation',
          'get_service_details',
          'get_window_info',
          'search_services'
        ]
      )
      assert.ok(listed.tools.every((tool) => tool.annotations?.readOnlyHint === true))

      const search = await client.callTool({
        name: 'search_services',
        arguments: { keyword: '社保' }
      })
      assert.equal(search.isError, undefined)
      assert.equal(search.content.length, 1)
      const searchPayload = JSON.parse(search.content[0].text)
      assert.equal(searchPayload.items[0].id, 1001)
      assert.equal(searchPayload.content, undefined)

      const details = await client.callTool({
        name: 'get_service_details',
        arguments: { id: 1001 }
      })
      assert.equal(JSON.parse(details.content[0].text).service.is_demo, true)

      const materials = await client.callTool({
        name: 'get_material_checklist',
        arguments: { itemId: 1001 }
      })
      assert.equal(JSON.parse(materials.content[0].text).required.length, 1)

      const processNavigation = await client.callTool({
        name: 'get_process_navigation',
        arguments: { itemId: 1001 }
      })
      assert.equal(processNavigation.content.length, 1)
      const processPayload = JSON.parse(processNavigation.content[0].text)
      assert.equal(processPayload.steps[0].code, 'SUBMIT')
      assert.equal(processPayload.content, undefined)

      const windowInfo = await client.callTool({
        name: 'get_window_info',
        arguments: { itemId: 1001, windowId: 'HRSS-CENTER-01' }
      })
      assert.equal(windowInfo.content.length, 1)
      const windowPayload = JSON.parse(windowInfo.content[0].text)
      assert.equal(windowPayload.windows[0].id, 'HRSS-CENTER-01')
      assert.equal(windowPayload.content, undefined)
      assert.equal(observedGovAuthorization, `Bearer ${GOV_TOKEN}`)
    } finally {
      await transport.terminateSession()
      await client.close()
    }
    assert.equal(sessions.size, 0)
  })

  test('rejects new sessions at capacity and releases capacity after termination', async () => {
    const created = createApp({
      internalToken: MCP_TOKEN,
      govApiBaseUrl: fakeGovBaseUrl,
      govApiToken: GOV_TOKEN,
      maxSessions: 1,
      logger: { error() {} }
    })
    const server = http.createServer(created.app)
    await listen(server)
    const url = new URL(`http://127.0.0.1:${server.address().port}/mcp`)
    const first = new Client({ name: 'capacity-one', version: '0.1.0' })
    const firstTransport = new StreamableHTTPClientTransport(url, {
      requestInit: { headers: { authorization: `Bearer ${MCP_TOKEN}` } }
    })
    const second = new Client({ name: 'capacity-two', version: '0.1.0' })
    const secondTransport = new StreamableHTTPClientTransport(url, {
      requestInit: { headers: { authorization: `Bearer ${MCP_TOKEN}` } }
    })
    try {
      await first.connect(firstTransport)
      assert.equal(created.sessions.size, 1)
      await assert.rejects(second.connect(secondTransport))
      assert.equal(created.sessions.size, 1)
      await firstTransport.terminateSession()
      await first.close()
      assert.equal(created.sessions.size, 0)
    } finally {
      await second.close().catch(() => {})
      await created.closeSessions()
      await close(server)
    }
  })

  test('expires an abandoned idle session', async () => {
    const created = createApp({
      internalToken: MCP_TOKEN,
      govApiBaseUrl: fakeGovBaseUrl,
      govApiToken: GOV_TOKEN,
      sessionTtlMs: 30,
      logger: { error() {} }
    })
    const server = http.createServer(created.app)
    await listen(server)
    const client = new Client({ name: 'ttl-client', version: '0.1.0' })
    const transport = new StreamableHTTPClientTransport(
      new URL(`http://127.0.0.1:${server.address().port}/mcp`),
      { requestInit: { headers: { authorization: `Bearer ${MCP_TOKEN}` } } }
    )
    try {
      await client.connect(transport)
      assert.equal(created.sessions.size, 1)
      await new Promise((resolve) => setTimeout(resolve, 100))
      assert.equal(created.sessions.size, 0)
    } finally {
      await client.close().catch(() => {})
      await created.closeSessions()
      await close(server)
    }
  })
})
