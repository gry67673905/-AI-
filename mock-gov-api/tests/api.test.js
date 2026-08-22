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
    assert.equal(body.total, 2)
    assert.deepEqual(body.items.map((item) => item.id), [1001, 1004])
    assert.ok(body.items.every((item) => item.materials === undefined))

    const naturalQuestionResponse = await fetch(
      `${baseUrl}/services?keyword=${encodeURIComponent('办理社会保障卡需要准备哪些材料？')}`,
      { headers: { authorization: `Bearer ${TOKEN}` } }
    )
    assert.equal(naturalQuestionResponse.status, 200)
    const naturalQuestion = await naturalQuestionResponse.json()
    assert.equal(naturalQuestion.total, 1)
    assert.equal(naturalQuestion.items[0].id, 1001)
  })

  test('prefers specific matters in natural-language aliases', async () => {
    const headers = { authorization: `Bearer ${TOKEN}` }
    const cases = [
      ['企业如何办理劳动合同备案', 1005],
      ['企业社保登记怎么办', 1004],
      ['个体户注册怎么办', 1003]
    ]
    for (const [question, expectedId] of cases) {
      const response = await fetch(
        `${baseUrl}/services?keyword=${encodeURIComponent(question)}`,
        { headers }
      )
      assert.equal(response.status, 200)
      const body = await response.json()
      assert.equal(body.total, 1)
      assert.equal(body.items[0].id, expectedId)
    }
  })

  test('exposes six personal and business demo services', async () => {
    const response = await fetch(`${baseUrl}/services`, {
      headers: { authorization: `Bearer ${TOKEN}` }
    })
    assert.equal(response.status, 200)
    const body = await response.json()
    assert.equal(body.total, 6)
    assert.deepEqual(
      [...new Set(body.items.flatMap((item) => item.applicant_types))].sort(),
      ['BUSINESS', 'PERSONAL']
    )
    assert.ok(body.items.every((item) => item.is_demo === true))
    assert.ok(body.items.every((item) => item.appointment && item.fee && item.delivery))
    assert.ok(body.items.every((item) => item.materials === undefined))
    assert.ok(body.items.some((item) => item.fee.required === true))
    assert.ok(body.items.some((item) => item.delivery.options.includes('DEMO_MAIL')))
    assert.ok(body.items
      .filter((item) => item.id >= 1004)
      .every((item) => item.delivery.mail_supported === false))
    assert.ok(body.items
      .filter((item) => item.id <= 1003)
      .every((item) => item.delivery.mail_supported === true))
    assert.ok(body.items
      .filter((item) => item.appointment.supported === false)
      .every((item) => item.appointment.channels.length === 0))
  })

  test('keeps legacy process summaries aligned with structured process steps', async () => {
    const headers = { authorization: `Bearer ${TOKEN}` }
    for (const itemId of [1001, 1002, 1003, 1004, 1005, 1006]) {
      const detailsResponse = await fetch(`${baseUrl}/services/${itemId}`, { headers })
      const processResponse = await fetch(`${baseUrl}/services/${itemId}/process`, { headers })
      assert.equal(detailsResponse.status, 200)
      assert.equal(processResponse.status, 200)
      const details = await detailsResponse.json()
      const process = await processResponse.json()
      assert.deepEqual(details.service.process, process.steps.map((step) => step.name))
    }
  })

  test('returns service details and split material checklist', async () => {
    const headers = { authorization: `Bearer ${TOKEN}` }
    const detailsResponse = await fetch(`${baseUrl}/services/1002`, { headers })
    assert.equal(detailsResponse.status, 200)
    const details = await detailsResponse.json()
    assert.equal(details.service.name, '居民身份证丢失补领')
    assert.equal(details.service.is_demo, true)
    assert.ok(Array.isArray(details.service.eligibility_rule.eq))

    const materialsResponse = await fetch(`${baseUrl}/services/1003/materials`, { headers })
    assert.equal(materialsResponse.status, 200)
    const materials = await materialsResponse.json()
    assert.equal(materials.item_id, 1003)
    assert.equal(materials.required.length, 2)
    assert.equal(materials.conditional.length, 1)
    assert.equal(materials.optional.length, 0)
    assert.deepEqual(materials.conditional[0].condition, {
      eq: ['application.submitted_by_agent', true]
    })
    assert.equal(materials.is_demo, true)
  })

  test('returns process navigation with appointment, fee and delivery semantics', async () => {
    const response = await fetch(`${baseUrl}/services/1002/process`, {
      headers: { authorization: `Bearer ${TOKEN}` }
    })
    assert.equal(response.status, 200)
    const body = await response.json()
    assert.equal(body.item_id, 1002)
    assert.equal(body.appointment.required, true)
    assert.equal(body.fee.required, true)
    assert.equal(body.fee.amount_yuan, 40)
    assert.ok(body.delivery.options.includes('DEMO_MAIL'))
    assert.deepEqual(body.steps.map((item) => item.order), [1, 2, 3, 4, 5])
    assert.ok(body.steps.some((item) => item.code === 'PAY'))
    assert.equal(body.is_demo, true)
  })

  test('returns all windows or one validated window', async () => {
    const headers = { authorization: `Bearer ${TOKEN}` }
    const allResponse = await fetch(`${baseUrl}/services/1006/windows`, { headers })
    assert.equal(allResponse.status, 200)
    const all = await allResponse.json()
    assert.equal(all.total, 1)
    assert.equal(all.windows[0].coordinate_type, 'DEMO_GCJ02')
    assert.equal(all.windows[0].is_demo, true)

    const oneResponse = await fetch(
      `${baseUrl}/services/1006/windows?window_id=FUND-CENTER-01`,
      { headers }
    )
    assert.equal(oneResponse.status, 200)
    assert.equal((await oneResponse.json()).windows[0].id, 'FUND-CENTER-01')

    const missingResponse = await fetch(
      `${baseUrl}/services/1006/windows?window_id=UNKNOWN`,
      { headers }
    )
    assert.equal(missingResponse.status, 404)
    assert.equal((await missingResponse.json()).error.code, 'window_not_found')
  })

  test('returns a structured 404 for an unknown service', async () => {
    const response = await fetch(`${baseUrl}/services/9999`, {
      headers: { authorization: `Bearer ${TOKEN}` }
    })
    assert.equal(response.status, 404)
    assert.equal((await response.json()).error.code, 'service_not_found')
  })
})
