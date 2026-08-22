const DEMO_FORMATS = Object.freeze(['application/pdf', 'image/jpeg', 'image/png'])

function material(id, name, requirement, note, condition = null, triggerReason = null) {
  return {
    id,
    name,
    requirement,
    required: requirement === 'REQUIRED',
    condition,
    trigger_reason: triggerReason,
    note,
    accepted_formats: DEMO_FORMATS
  }
}

function step(order, code, name, actor, description, expectedDuration) {
  return { order, code, name, actor, description, expected_duration: expectedDuration }
}

function window(id, name, department, district, address, appointmentSupported, longitude, latitude) {
  return {
    id,
    name,
    department,
    district,
    address,
    service_hours: '演示时间：工作日 09:00-17:00',
    appointment_supported: appointmentSupported,
    longitude,
    latitude,
    coordinate_type: 'DEMO_GCJ02',
    phone: '0000-0000000',
    is_demo: true
  }
}

function appointment(supported, required, channels, notice) {
  return { supported, required, channels, notice }
}

function delivery(options, feeNotice) {
  return {
    supported: options.length > 0,
    mail_supported: options.includes('DEMO_MAIL'),
    options,
    fee_notice: feeNotice
  }
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value
  Object.freeze(value)
  for (const child of Object.values(value)) deepFreeze(child)
  return value
}

const rawServices = [
  {
    id: 1001,
    code: 'DEMO-SS-CARD-001',
    name: '社会保障卡申领',
    category: '社会保障',
    department: '演示市人力资源和社会保障局',
    service_object: '在演示市就业或居住的居民',
    applicant_types: ['PERSONAL'],
    summary: '申领实体社会保障卡。所有内容均为联调演示数据，不可作为真实办事依据。',
    conditions: ['申请人持有有效身份证明', '未在演示市重复申领社会保障卡'],
    eligibility_rule: {
      all: [
        { exists: ['applicant.valid_identity_document'] },
        { eq: ['applicant.has_duplicate_demo_card', false] }
      ]
    },
    processing_time: '演示时限：10 个工作日',
    appointment: appointment(true, false, ['ONLINE', 'WINDOW'], '可预约演示窗口，也可直接在线提交。'),
    fee: { required: false, amount_yuan: 0, currency: 'CNY', label: '演示免费' },
    delivery: delivery(['WINDOW_PICKUP', 'DEMO_MAIL'], '演示邮寄不产生真实费用。'),
    process: ['提交申请', '材料审核', '模拟制卡', '领取结果'],
    process_steps: [
      step(1, 'SUBMIT', '提交申请', 'APPLICANT', '填写表单并上传演示材料。', '即时'),
      step(2, 'REVIEW', '材料审核', 'STAFF', '工作人员核对申请信息和材料。', '3 个演示工作日'),
      step(3, 'PRODUCE', '模拟制卡', 'SYSTEM', '生成演示制卡结果。', '6 个演示工作日'),
      step(4, 'DELIVER', '领取结果', 'APPLICANT', '窗口领取或选择演示邮寄。', '1 个演示工作日')
    ],
    notice: '演示数据：实际要求请以当地人社部门最新规定为准。',
    materials: [
      material('ss-1', '有效身份证件', 'REQUIRED', '演示要求：核验原件'),
      material('ss-2', '近期免冠照片', 'REQUIRED', '演示要求：电子版'),
      material(
        'ss-3',
        '监护关系证明',
        'CONDITIONAL',
        '仅使用合成演示材料',
        { eq: ['applicant.is_minor', true] },
        '未成年人由监护人代办时提供'
      )
    ],
    windows: [
      window('HRSS-CENTER-01', '演示市民服务中心人社窗口', '演示市人力资源和社会保障局',
        '演示城区', '演示大道 100 号 A 区 01 窗口', true, 116.400101, 39.900101)
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
    applicant_types: ['PERSONAL'],
    summary: '办理居民身份证丢失补领。所有身份核验、缴费和结果均为模拟。',
    conditions: ['申请人能够完成演示身份核验'],
    eligibility_rule: { eq: ['verification.demo_identity_passed', true] },
    processing_time: '演示时限：20 个工作日',
    appointment: appointment(true, true, ['WINDOW'], '提交前必须选择演示户政窗口和预约时段。'),
    fee: { required: true, amount_yuan: 40, currency: 'CNY', label: '演示工本费，不发生真实扣款' },
    delivery: delivery(['WINDOW_PICKUP', 'DEMO_MAIL'], '邮寄方式和费用均为模拟。'),
    process: ['预约窗口', '身份核验', '信息审核', '模拟缴费', '领取结果'],
    process_steps: [
      step(1, 'APPOINT', '预约窗口', 'APPLICANT', '选择演示窗口和可用时段。', '即时'),
      step(2, 'VERIFY', '身份核验', 'SYSTEM', '仅推进模拟核验状态，不采集生物信息。', '即时'),
      step(3, 'REVIEW', '信息审核', 'STAFF', '工作人员核对演示材料。', '3 个演示工作日'),
      step(4, 'PAY', '模拟缴费', 'APPLICANT', '完成可失败重试的本地模拟支付。', '即时'),
      step(5, 'DELIVER', '领取结果', 'APPLICANT', '窗口领取或选择演示邮寄。', '17 个演示工作日')
    ],
    notice: '演示数据：异地办理范围与收费标准请咨询当地公安机关。',
    materials: [
      material('id-1', '居民户口簿或其他有效身份证明', 'REQUIRED', '演示要求：提供一种即可'),
      material('id-2', '丢失情况说明', 'REQUIRED', '使用合成信息填写'),
      material('id-3', '原居民身份证', 'OPTIONAL', '如已找回可携带')
    ],
    windows: [
      window('POLICE-HUKOU-01', '演示市民服务中心户政窗口', '演示市公安局',
        '演示城区', '演示大道 100 号 B 区 02 窗口', true, 116.400202, 39.900202)
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
    applicant_types: ['PERSONAL'],
    summary: '办理个体工商户设立登记。登记结果和电子证照均为演示数据。',
    conditions: ['申请人具备相应民事行为能力', '经营场所符合演示登记要求'],
    eligibility_rule: {
      all: [
        { eq: ['applicant.has_civil_capacity', true] },
        { exists: ['business.premises_address'] }
      ]
    },
    processing_time: '演示时限：3 个工作日',
    appointment: appointment(true, false, ['ONLINE', 'WINDOW'], '优先在线办理，需要咨询时可预约窗口。'),
    fee: { required: false, amount_yuan: 0, currency: 'CNY', label: '演示免费' },
    delivery: delivery(['DIGITAL_RESULT', 'WINDOW_PICKUP', 'DEMO_MAIL'], '电子结果仅用于演示。'),
    process: ['信息预检', '提交申请', '登记审核', '领取结果'],
    process_steps: [
      step(1, 'PRECHECK', '信息预检', 'SYSTEM', '校验演示名称、经营范围和地址字段。', '即时'),
      step(2, 'SUBMIT', '提交申请', 'APPLICANT', '确认表单及材料完整性。', '即时'),
      step(3, 'REVIEW', '登记审核', 'STAFF', '市场监管工作人员执行演示审核。', '2 个演示工作日'),
      step(4, 'DELIVER', '领取结果', 'APPLICANT', '下载演示电子结果或选择线下方式。', '1 个演示工作日')
    ],
    notice: '演示数据：涉及许可经营项目时还需按实际规定取得许可。',
    materials: [
      material('bl-1', '经营者身份证明', 'REQUIRED', '演示要求：核验原件'),
      material('bl-2', '经营场所使用证明', 'REQUIRED', '演示要求：地址清晰完整'),
      material('bl-3', '委托代理证明', 'CONDITIONAL', '仅使用合成演示材料',
        { eq: ['application.submitted_by_agent', true] }, '委托代理人办理时提供')
    ],
    windows: [
      window('MARKET-CENTER-01', '演示市民服务中心市场监管窗口', '演示市市场监督管理局',
        '演示城区', '演示大道 100 号 C 区 03 窗口', true, 116.400303, 39.900303)
    ],
    is_demo: true
  },
  {
    id: 1004,
    code: 'DEMO-ENTERPRISE-SS-001',
    name: '企业社会保险登记',
    category: '企业服务',
    department: '演示市人力资源和社会保障局',
    service_object: '在演示市注册并用工的企业',
    applicant_types: ['BUSINESS'],
    summary: '为企业办理社会保险登记。企业、人员和登记结果均为合成演示数据。',
    conditions: ['企业处于演示正常登记状态', '经办人已获得企业授权'],
    eligibility_rule: {
      all: [
        { eq: ['business.registration_status', 'ACTIVE'] },
        { eq: ['operator.authorized', true] }
      ]
    },
    processing_time: '演示时限：2 个工作日',
    appointment: appointment(false, false, [], '本事项仅演示在线办理，不提供预约。'),
    fee: { required: false, amount_yuan: 0, currency: 'CNY', label: '演示免费' },
    delivery: delivery(['DIGITAL_RESULT'], '登记回执仅为演示电子结果。'),
    process: ['企业资格预检', '提交登记', '登记审核', '生成回执'],
    process_steps: [
      step(1, 'PRECHECK', '企业资格预检', 'SYSTEM', '校验演示企业状态和经办授权。', '即时'),
      step(2, 'SUBMIT', '提交登记', 'APPLICANT', '提交企业与用工信息。', '即时'),
      step(3, 'REVIEW', '登记审核', 'STAFF', '人社工作人员处理演示待办。', '2 个演示工作日'),
      step(4, 'RESULT', '生成回执', 'SYSTEM', '生成演示电子回执。', '即时')
    ],
    notice: '演示数据：实际参保登记口径以当地人社和税务部门规定为准。',
    materials: [
      material('ess-1', '企业登记信息页', 'REQUIRED', '使用合成统一社会信用代码'),
      material('ess-2', '经办人授权书', 'REQUIRED', '使用合成企业与人员信息'),
      material('ess-3', '分支机构关系说明', 'CONDITIONAL', '仅用于条件材料判断',
        { eq: ['business.is_branch', true] }, '分支机构办理时提供')
    ],
    windows: [
      window('HRSS-BUSINESS-01', '演示市企业服务中心人社窗口', '演示市人力资源和社会保障局',
        '演示新区', '演示创新路 200 号 04 窗口', false, 116.410404, 39.910404)
    ],
    is_demo: true
  },
  {
    id: 1005,
    code: 'DEMO-LABOR-CONTRACT-001',
    name: '劳动合同备案',
    category: '企业服务',
    department: '演示市人力资源和社会保障局',
    service_object: '需要备案劳动合同的演示企业',
    applicant_types: ['BUSINESS'],
    summary: '提交劳动合同备案并跟踪审核结果。合同与人员信息必须为合成演示数据。',
    conditions: ['企业已完成演示社会保险登记', '劳动合同字段完整'],
    eligibility_rule: {
      all: [
        { eq: ['business.demo_social_insurance_registered', true] },
        { exists: ['contract.employee_demo_id'] },
        { exists: ['contract.effective_date'] }
      ]
    },
    processing_time: '演示时限：1 个工作日',
    appointment: appointment(false, false, [], '本事项仅演示在线办理，不提供预约。'),
    fee: { required: false, amount_yuan: 0, currency: 'CNY', label: '演示免费' },
    delivery: delivery(['DIGITAL_RESULT'], '备案结果仅供系统联调。'),
    process: ['资格预检', '提交备案', '备案审核', '生成结果'],
    process_steps: [
      step(1, 'PRECHECK', '资格预检', 'SYSTEM', '检查企业状态和必要字段。', '即时'),
      step(2, 'SUBMIT', '提交备案', 'APPLICANT', '上传合成合同材料并提交。', '即时'),
      step(3, 'REVIEW', '备案审核', 'STAFF', '工作人员批准或要求补正。', '1 个演示工作日'),
      step(4, 'RESULT', '生成结果', 'SYSTEM', '生成演示备案编号和电子回执。', '即时')
    ],
    notice: '禁止上传真实劳动合同、身份证号、薪资或联系方式。',
    materials: [
      material('lc-1', '劳动合同演示件', 'REQUIRED', '必须使用完全合成的人员和薪资信息'),
      material('lc-2', '企业经办人授权书', 'REQUIRED', '使用合成企业信息'),
      material('lc-3', '集体合同说明', 'CONDITIONAL', '仅用于条件材料判断',
        { eq: ['contract.type', 'COLLECTIVE'] }, '合同类型为集体合同时提供')
    ],
    windows: [
      window('LABOR-SERVICE-01', '演示市企业服务中心劳动关系窗口', '演示市人力资源和社会保障局',
        '演示新区', '演示创新路 200 号 05 窗口', false, 116.410505, 39.910505)
    ],
    is_demo: true
  },
  {
    id: 1006,
    code: 'DEMO-HOUSING-FUND-001',
    name: '单位住房公积金缴存登记与演示缴付',
    category: '住房公积金',
    department: '演示市住房公积金管理中心',
    service_object: '需要建立住房公积金缴存关系的演示单位',
    applicant_types: ['BUSINESS'],
    summary: '完成单位缴存登记并体验金额计算和模拟缴付，不连接真实公积金或银行系统。',
    conditions: ['单位登记状态正常', '缴存基数与比例已填写'],
    eligibility_rule: {
      all: [
        { eq: ['business.registration_status', 'ACTIVE'] },
        { exists: ['fund.contribution_base'] },
        { gte: ['fund.contribution_ratio', 0.05] },
        { lte: ['fund.contribution_ratio', 0.12] }
      ]
    },
    processing_time: '演示时限：2 个工作日',
    appointment: appointment(true, false, ['ONLINE', 'WINDOW'], '可在线提交，也可预约演示窗口咨询。'),
    fee: {
      required: true,
      amount_yuan: null,
      currency: 'CNY',
      calculation: '演示缴存基数 × 演示缴存比例，仅生成模拟支付订单',
      label: '演示缴付款，不发生真实扣款'
    },
    delivery: delivery(['DIGITAL_RESULT'], '缴付凭证仅为演示电子结果。'),
    process: ['单位资格预检', '提交登记', '登记审核', '模拟缴付', '生成凭证'],
    process_steps: [
      step(1, 'PRECHECK', '单位资格预检', 'SYSTEM', '校验演示单位状态、基数和比例。', '即时'),
      step(2, 'SUBMIT', '提交登记', 'APPLICANT', '提交单位及合成人员汇总信息。', '即时'),
      step(3, 'REVIEW', '登记审核', 'STAFF', '公积金工作人员处理演示待办。', '2 个演示工作日'),
      step(4, 'PAY', '模拟缴付', 'APPLICANT', '生成并推进本地模拟支付订单。', '即时'),
      step(5, 'RESULT', '生成凭证', 'SYSTEM', '生成演示电子凭证。', '即时')
    ],
    notice: '所有金额、人员和单位信息均为合成演示数据。',
    materials: [
      material('hf-1', '单位登记信息页', 'REQUIRED', '使用合成统一社会信用代码'),
      material('hf-2', '缴存人员汇总表', 'REQUIRED', '不得包含任何真实个人信息'),
      material('hf-3', '委托扣款授权演示件', 'CONDITIONAL', '不填写真实银行账户',
        { eq: ['fund.payment_mode', 'DEMO_DEBIT'] }, '选择模拟委托扣款方式时提供')
    ],
    windows: [
      window('FUND-CENTER-01', '演示市民服务中心公积金窗口', '演示市住房公积金管理中心',
        '演示城区', '演示大道 100 号 D 区 06 窗口', true, 116.400606, 39.900606)
    ],
    is_demo: true
  }
]

export const services = deepFreeze(rawServices)

export function publicService(service) {
  const { materials, process_steps, windows, eligibility_rule, ...details } = service
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
    ['市监', '市场监管'],
    ['企业', '企业服务'],
    ['合同', '企业服务'],
    ['公积金', '住房公积金']
  ])

  // Prefer a specific matter name over a broad category. Natural-language
  // questions such as “企业如何办理劳动合同备案” must not fall through to the
  // first item in the generic 企业服务 category.
  const matterAliases = [
    { terms: ['企业社保', '职工社会保险', '企业职工社保'], ids: [1004] },
    { terms: ['劳动合同', '合同备案'], ids: [1005] },
    { terms: ['单位公积金', '公积金登记', '公积金缴付'], ids: [1006] },
    { terms: ['个体户', '个体工商', '营业执照'], ids: [1003] },
    { terms: ['身份证'], ids: [1002] },
    { terms: ['社保卡', '社会保障卡'], ids: [1001] },
    { terms: ['公积金'], ids: [1006] },
    { terms: ['社保', '社会保障'], ids: [1001, 1004] }
  ]
  const specificIds = matterAliases
    .find(({ terms }) => terms.some((term) => normalizedKeyword.includes(term)))
    ?.ids

  return services.filter((service) => {
    const searchable = [service.name, service.code, service.category, service.department,
      service.service_object, service.summary, ...service.conditions]
      .join(' ').toLocaleLowerCase('zh-CN')
    const serviceTerms = [service.name, service.category]
      .map((value) => value.toLocaleLowerCase('zh-CN'))
    const aliasCategory = [...aliases.entries()]
      .find(([alias]) => normalizedKeyword.includes(alias))?.[1]
    const specificMatterHit = !specificIds || specificIds.includes(service.id)
    const keywordHit = !normalizedKeyword ||
      Boolean(specificIds) ||
      searchable.includes(normalizedKeyword) ||
      serviceTerms.some((term) => normalizedKeyword.includes(term)) ||
      service.category === aliases.get(normalizedKeyword) ||
      service.category === aliasCategory
    const categoryHit = !normalizedCategory || service.category.toLocaleLowerCase('zh-CN') === normalizedCategory
    return specificMatterHit && keywordHit && categoryHit
  })
}
