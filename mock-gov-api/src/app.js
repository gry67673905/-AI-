import crypto from 'node:crypto'
import express from 'express'
import { publicService, searchServices, services } from './data.js'

function tokensMatch(expected, provided) {
  if (!expected || !provided) return false
  const expectedBuffer = Buffer.from(expected)
  const providedBuffer = Buffer.from(provided)
  return expectedBuffer.length === providedBuffer.length &&
    crypto.timingSafeEqual(expectedBuffer, providedBuffer)
}

function bearerToken(header) {
  if (typeof header !== 'string') return null
  const match = /^Bearer\s+(.+)$/i.exec(header.trim())
  return match?.[1] ?? null
}

export function createApp({ token, logger = console } = {}) {
  if (!token) throw new Error('GOV_API_TOKEN is required')

  const app = express()
  app.disable('x-powered-by')
  app.use(express.json({ limit: '16kb' }))

  app.get('/health', (_request, response) => {
    response.json({ status: 'ok', service: 'mock-gov-api', is_demo: true })
  })

  app.use((request, response, next) => {
    if (!tokensMatch(token, bearerToken(request.get('authorization')))) {
      return response.status(401).json({
        error: { code: 'unauthorized', message: '需要有效的 Bearer Token。' },
        is_demo: true
      })
    }
    next()
  })

  app.get('/services', (request, response) => {
    const keyword = typeof request.query.keyword === 'string' ? request.query.keyword : ''
    const category = typeof request.query.category === 'string' ? request.query.category : ''
    if (keyword.length > 100 || category.length > 100) {
      return response.status(400).json({
        error: { code: 'invalid_query', message: '关键词和分类不能超过 100 个字符。' },
        is_demo: true
      })
    }
    const items = searchServices({ keyword, category }).map(publicService)
    response.json({ items, total: items.length, is_demo: true })
  })

  function findService(request, response) {
    const id = Number(request.params.id)
    const service = services.find((item) => item.id === id)
    if (!service) {
      response.status(404).json({
        error: { code: 'service_not_found', message: `未找到事项 ID ${request.params.id}。` },
        is_demo: true
      })
      return null
    }
    return service
  }

  app.get('/services/:id/materials', (request, response) => {
    const service = findService(request, response)
    if (!service) return
    response.json({
      item_id: service.id,
      item_name: service.name,
      required: service.materials.filter((item) => item.requirement === 'REQUIRED'),
      conditional: service.materials.filter((item) => item.requirement === 'CONDITIONAL'),
      optional: service.materials.filter((item) => item.requirement === 'OPTIONAL'),
      notice: service.notice,
      is_demo: true
    })
  })

  app.get('/services/:id/process', (request, response) => {
    const service = findService(request, response)
    if (!service) return
    response.json({
      item_id: service.id,
      item_name: service.name,
      processing_time: service.processing_time,
      steps: service.process_steps,
      appointment: service.appointment,
      fee: service.fee,
      delivery: service.delivery,
      notice: service.notice,
      is_demo: true
    })
  })

  app.get('/services/:id/windows', (request, response) => {
    const service = findService(request, response)
    if (!service) return
    const windowId = typeof request.query.window_id === 'string' ? request.query.window_id.trim() : ''
    if (windowId.length > 64) {
      return response.status(400).json({
        error: { code: 'invalid_query', message: '窗口 ID 不能超过 64 个字符。' },
        is_demo: true
      })
    }
    const windows = windowId
      ? service.windows.filter((item) => item.id === windowId)
      : service.windows
    if (windowId && windows.length === 0) {
      return response.status(404).json({
        error: { code: 'window_not_found', message: `未找到窗口 ID ${windowId}。` },
        is_demo: true
      })
    }
    response.json({
      item_id: service.id,
      item_name: service.name,
      windows,
      total: windows.length,
      map_notice: '坐标、地址、电话和服务时间均为演示数据。',
      is_demo: true
    })
  })

  app.get('/services/:id', (request, response) => {
    const service = findService(request, response)
    if (!service) return
    response.json({ service, is_demo: true })
  })

  app.use((request, response) => {
    response.status(404).json({
      error: { code: 'not_found', message: '接口不存在。' },
      is_demo: true
    })
  })

  app.use((error, _request, response, _next) => {
    logger.error?.('mock-gov-api request failed', { name: error?.name })
    response.status(500).json({
      error: { code: 'internal_error', message: '模拟政务接口发生内部错误。' },
      is_demo: true
    })
  })

  return app
}
