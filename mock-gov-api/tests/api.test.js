import assert from 'node:assert/strict'
import { after, before, describe, test } from 'node:test'
import { createApp } from '../src/app.js'

const TOKEN = 'test-gov-api-token'
let server
let baseUrl

before(async () => {
  const app = createApp({ token: TOKEN, logger: { error() {} } })
  server = app.listen(0, '127.0.0.1')
  await new Promise((resolve, reject) => {
    server.once('listening', resolve)
    server.once('error', reject)
  })
  const address = server.address()
  baseUrl = `http://127.0.0.1:${address.port}`
})

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve))
})

describe('mock government API', () => {
  test('health is public and marked as demo data', async () => {
    const response = await fetch(`${baseUrl}/health`)
    assert.equal(response.status, 200)
    assert.deepEqual(await response.json(), {
      status: 'ok', service: 'mock-gov-api', is_demo: true
    })
  })

  test('business endpoints reject missing and incorrect tokens', async () => {
    for (const authorization of [undefined, 'Bearer incorrect']) {
      const response = await fetch(`${baseUrl}/services`, {
        headers: authorization ? { authorization } : {}
      })
      assert.equal(response.status, 401)
      assert.equal((await response.json()).error.code, 'unauthorized')
    }
  })

  test('searches the demo service catalogue', async () => {
    const response = await fetch(`${baseUrl}/services?keyword=${encodeURIComponent('社保')}`, {
      headers: { authorization: `Bearer ${TOKEN}` }
    })
    assert.equal(response.status, 200)
    const body = await response.json()
    assert.equal(body.is_demo, true)
    assert.equal(body.total, 1)
    assert.equal(body.items[0].id, 1001)
    assert.equal(body.items[0].materials, undefined)

    const naturalQuestionResponse = await fetch(
      `${baseUrl}/services?keyword=${encodeURIComponent('办理社会保障卡需要准备哪些材料？')}`,
      { headers: { authorization: `Bearer ${TOKEN}` } }
    )
    assert.equal(naturalQuestionResponse.status, 200)
    const naturalQuestion = await naturalQuestionResponse.json()
    assert.equal(naturalQuestion.total, 1)
    assert.equal(naturalQuestion.items[0].id, 1001)
  })

  test('returns service details and split material checklist', async () => {
    const headers = { authorization: `Bearer ${TOKEN}` }
    const detailsResponse = await fetch(`${baseUrl}/services/1002`, { headers })
    assert.equal(detailsResponse.status, 200)
    const details = await detailsResponse.json()
    assert.equal(details.service.name, '居民身份证丢失补领')
    assert.equal(details.service.is_demo, true)

    const materialsResponse = await fetch(`${baseUrl}/services/1003/materials`, { headers })
    assert.equal(materialsResponse.status, 200)
    const materials = await materialsResponse.json()
    assert.equal(materials.item_id, 1003)
    assert.equal(materials.required.length, 2)
    assert.equal(materials.optional.length, 1)
    assert.equal(materials.is_demo, true)
  })

  test('returns a structured 404 for an unknown service', async () => {
    const response = await fetch(`${baseUrl}/services/9999`, {
      headers: { authorization: `Bearer ${TOKEN}` }
    })
    assert.equal(response.status, 404)
    assert.equal((await response.json()).error.code, 'service_not_found')
  })
})
