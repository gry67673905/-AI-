export const services = Object.freeze([
  {
    id: 1001,
    code: 'DEMO-SS-CARD-001',
    name: '社会保障卡申领',
    category: '社会保障',
    department: '演示市人力资源和社会保障局',
    service_object: '在演示市就业或居住的居民',
    summary: '申领实体社会保障卡。所有内容均为联调演示数据，不可作为真实办事依据。',
    conditions: ['申请人持有有效身份证明', '未在演示市重复申领社会保障卡'],
    processing_time: '演示时限：10 个工作日',
    process: ['提交申请', '演示部门审核', '制卡', '领卡'],
    notice: '演示数据：实际要求请以当地人社部门最新规定为准。',
    materials: [
      { id: 'ss-1', name: '有效身份证件', required: true, note: '演示要求：核验原件' },
      { id: 'ss-2', name: '近期免冠照片', required: true, note: '演示要求：电子版' },
      { id: 'ss-3', name: '监护关系证明', required: false, note: '未成年人由监护人代办时提供' }
    ],
    is_demo: true
  },
  {
    id: 1002,
    code: 'DEMO-ID-REISSUE-001',
    name: '居民身份证丢失补领',
    category: '公安户政',
    department: '演示市公安局',
    service_object: '居民身份证丢失的居民',
    summary: '办理居民身份证丢失补领。所有内容均为联调演示数据，不可作为真实办事依据。',
    conditions: ['申请人能够完成身份核验'],
    processing_time: '演示时限：20 个工作日',
    process: ['身份核验', '采集信息', '缴纳演示工本费', '领取证件'],
    notice: '演示数据：异地办理范围与收费标准请咨询当地公安机关。',
    materials: [
      { id: 'id-1', name: '居民户口簿或其他有效身份证明', required: true, note: '演示要求：提供一种即可' },
      { id: 'id-2', name: '原居民身份证', required: false, note: '如已找回可携带' }
    ],
    is_demo: true
  },
  {
    id: 1003,
    code: 'DEMO-BL-REGISTER-001',
    name: '个体工商户设立登记',
    category: '市场监管',
    department: '演示市市场监督管理局',
    service_object: '拟在演示市从事个体经营的申请人',
    summary: '办理个体工商户设立登记。所有内容均为联调演示数据，不可作为真实办事依据。',
    conditions: ['申请人具备相应民事行为能力', '经营场所符合演示登记要求'],
    processing_time: '演示时限：3 个工作日',
    process: ['名称与经营范围确认', '提交设立申请', '演示部门审核', '领取营业执照'],
    notice: '演示数据：涉及许可经营项目时还需按实际规定取得许可。',
    materials: [
      { id: 'bl-1', name: '经营者身份证明', required: true, note: '演示要求：核验原件' },
      { id: 'bl-2', name: '经营场所使用证明', required: true, note: '演示要求：地址清晰完整' },
      { id: 'bl-3', name: '委托代理证明', required: false, note: '委托办理时提供' }
    ],
    is_demo: true
  }
])

export function publicService(service) {
  const { materials, ...details } = service
  return details
}

export function searchServices({ keyword = '', category = '' } = {}) {
  const normalizedKeyword = keyword.trim().toLocaleLowerCase('zh-CN')
  const normalizedCategory = category.trim().toLocaleLowerCase('zh-CN')
  const aliases = new Map([
    ['社保', '社会保障'],
    ['人社', '社会保障'],
    ['身份证', '公安户政'],
    ['户政', '公安户政'],
    ['营业执照', '市场监管'],
    ['市监', '市场监管']
  ])

  return services.filter((service) => {
    const searchable = [
      service.name,
      service.code,
      service.category,
      service.department,
      service.service_object,
      service.summary
    ].join(' ').toLocaleLowerCase('zh-CN')
    const serviceTerms = [service.name, service.category]
      .map((value) => value.toLocaleLowerCase('zh-CN'))
    const aliasCategory = [...aliases.entries()]
      .find(([alias]) => normalizedKeyword.includes(alias))?.[1]
    const keywordHit = !normalizedKeyword ||
      searchable.includes(normalizedKeyword) ||
      serviceTerms.some((term) => normalizedKeyword.includes(term)) ||
      service.category === aliases.get(normalizedKeyword) ||
      service.category === aliasCategory
    const categoryHit = !normalizedCategory || service.category.toLocaleLowerCase('zh-CN') === normalizedCategory
    return keywordHit && categoryHit
  })
}
