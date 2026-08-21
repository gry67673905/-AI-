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
        optional: [],
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

  test('lists and calls exactly the three read-only tools with one result wrapper', async () => {
    const client = new Client({ name: 'mcp-test-client', version: '0.1.0' })
    const transport = new StreamableHTTPClientTransport(new URL(`${mcpBaseUrl}/mcp`), {
      requestInit: { headers: { authorization: `Bearer ${MCP_TOKEN}` } }
    })

    try {
      await client.connect(transport)
      const listed = await client.listTools()
      assert.deepEqual(
        listed.tools.map((tool) => tool.name).sort(),
        ['get_material_checklist', 'get_service_details', 'search_services']
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
      assert.equal(observedGovAuthorization, `Bearer ${GOV_TOKEN}`)
    } finally {
      await client.close()
    }
  })
})
