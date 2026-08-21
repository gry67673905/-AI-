export class GovApiError extends Error {
  constructor(message, { status, code, cause } = {}) {
    super(message, { cause })
    this.name = 'GovApiError'
    this.status = status
    this.code = code
  }
}

export class GovApiClient {
  constructor({ baseUrl, token, fetchImpl = globalThis.fetch, timeoutMs = 5000 } = {}) {
    if (!baseUrl) throw new Error('GOV_API_BASE_URL is required')
    if (!token) throw new Error('GOV_API_TOKEN is required')
    if (typeof fetchImpl !== 'function') throw new TypeError('fetch implementation is required')
    this.baseUrl = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
    this.token = token
    this.fetchImpl = fetchImpl
    this.timeoutMs = timeoutMs
  }

  async request(path, query = {}) {
    const url = new URL(path.replace(/^\//, ''), this.baseUrl)
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }

    let response
    try {
      response = await this.fetchImpl(url, {
        method: 'GET',
        headers: {
          accept: 'application/json',
          authorization: `Bearer ${this.token}`
        },
        signal: AbortSignal.timeout(this.timeoutMs)
      })
    } catch (error) {
      throw new GovApiError('无法连接模拟政务 API。', { cause: error })
    }

    let body
    try {
      body = await response.json()
    } catch (error) {
      throw new GovApiError('模拟政务 API 返回了无效 JSON。', {
        status: response.status,
        cause: error
      })
    }

    if (!response.ok) {
      const code = typeof body?.error?.code === 'string' ? body.error.code : 'upstream_error'
      throw new GovApiError(`模拟政务 API 请求失败（HTTP ${response.status}，${code}）。`, {
        status: response.status,
        code
      })
    }
    return body
  }

  searchServices({ keyword = '', category = '' } = {}) {
    return this.request('services', { keyword, category })
  }

  getServiceDetails(id) {
    return this.request(`services/${encodeURIComponent(id)}`)
  }

  getMaterialChecklist(itemId) {
    return this.request(`services/${encodeURIComponent(itemId)}/materials`)
  }
}
