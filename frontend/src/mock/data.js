// 模拟数据：政务事项 / 部门 / 窗口 / 工作人员 / 材料 / 办件 / 咨询 / 知识库
// 后续接入真实后端时，本文件可整体替换为接口调用，数据结构保持一致。

export const departments = [
  { id: 1, name: '人力资源和社会保障局', code: 'RSJ', leader: '张三', phone: '0551-12345601', status: true },
  { id: 2, name: '公安局', code: 'GAJ', leader: '李四', phone: '0551-12345602', status: true },
  { id: 3, name: '市场监督管理局', code: 'SCJ', leader: '王五', phone: '0551-12345603', status: true },
  { id: 4, name: '住房公积金管理中心', code: 'GJJ', leader: '赵六', phone: '0551-12345604', status: true },
  { id: 5, name: '民政局', code: 'MZJ', leader: '钱七', phone: '0551-12345605', status: true },
  { id: 6, name: '自然资源和规划局', code: 'ZRJ', leader: '孙八', phone: '0551-12345606', status: true },
  { id: 7, name: '公安局交通警察支队', code: 'JJZ', leader: '周九', phone: '0551-12345607', status: true }
]

export const windows = [
  { id: 1, name: '综合窗口1号', deptId: 1, location: '政务大厅一层A区', serviceScope: '社保、医保、就业', status: true },
  { id: 2, name: '综合窗口2号', deptId: 1, location: '政务大厅一层A区', serviceScope: '养老、工伤', status: true },
  { id: 3, name: '户政窗口1号', deptId: 2, location: '政务大厅一层B区', serviceScope: '户籍、身份证、居住证', status: true },
  { id: 4, name: '户政窗口2号', deptId: 2, location: '政务大厅一层B区', serviceScope: '出入境', status: true },
  { id: 5, name: '市场监管窗口', deptId: 3, location: '政务大厅二层C区', serviceScope: '营业执照、食品经营', status: true },
  { id: 6, name: '公积金窗口', deptId: 4, location: '政务大厅二层D区', serviceScope: '公积金提取、贷款', status: true },
  { id: 7, name: '民政窗口', deptId: 5, location: '政务大厅二层E区', serviceScope: '婚姻登记、老龄优待', status: true },
  { id: 8, name: '不动产登记窗口', deptId: 6, location: '政务大厅三层F区', serviceScope: '不动产登记、转移', status: true },
  { id: 9, name: '车驾管窗口', deptId: 7, location: '车管所服务大厅', serviceScope: '驾驶证、行驶证', status: true }
]

export const staffs = [
  { id: 1, name: '刘芳', deptId: 1, windowId: 1, role: '窗口受理员', phone: '13800000001', status: true },
  { id: 2, name: '陈明', deptId: 1, windowId: 2, role: '窗口受理员', phone: '13800000002', status: true },
  { id: 3, name: '王丽', deptId: 2, windowId: 3, role: '户政民警', phone: '13800000003', status: true },
  { id: 4, name: '张强', deptId: 2, windowId: 4, role: '民警', phone: '13800000004', status: true },
  { id: 5, name: '李娜', deptId: 3, windowId: 5, role: '审批员', phone: '13800000005', status: true },
  { id: 6, name: '赵敏', deptId: 4, windowId: 6, role: '经办员', phone: '13800000006', status: true },
  { id: 7, name: '孙浩', deptId: 5, windowId: 7, role: '经办员', phone: '13800000007', status: true },
  { id: 8, name: '周婷', deptId: 6, windowId: 8, role: '登记员', phone: '13800000008', status: true },
  { id: 9, name: '吴刚', deptId: 7, windowId: 9, role: '车管民警', phone: '13800000009', status: true }
]

// 政务事项（含办理条件、流程、材料清单、注意事项）
export const items = [
  {
    id: 1,
    code: 'RS-SB-001',
    name: '社会保障卡申领',
    deptId: 1,
    category: '社会保障',
    serviceObject: '本市参保人员',
    legalBasis: '《中华人民共和国社会保险法》',
    hot: true,
    conditions: ['已参加本市社会保险', '本人身份证件有效', '未持有有效社会保障卡'],
    timeLimit: '10个工作日',
    charge: '免费',
    window: '综合窗口1号、2号',
    process: [
      { title: '提交申请', desc: '携带身份证到社保窗口或通过线上渠道提交申领申请' },
      { title: '信息核对', desc: '工作人员核对参保信息与身份信息' },
      { title: '制卡', desc: '提交制卡信息至制卡中心' },
      { title: '领卡激活', desc: '短信通知后凭身份证领卡，激活金融与社保功能' }
    ],
    materials: [
      { name: '居民身份证', required: true, copies: '原件+复印件1份', sample: '身份证正反面复印件', note: '在有效期内' },
      { name: '近期免冠白底彩照', required: true, copies: '1张', sample: '一寸照片', note: '6个月内拍摄' },
      { name: '社保卡申领登记表', required: true, copies: '1份', sample: '现场填写', note: '可线上预填' }
    ],
    notice: '首次申领免费；补换卡需缴纳工本费20元。'
  },
  {
    id: 2,
    code: 'RS-YL-002',
    name: '养老保险关系转移接续',
    deptId: 1,
    category: '社会保障',
    serviceObject: '跨地区就业参保人员',
    legalBasis: '《城镇企业职工基本养老保险关系转移接续暂行办法》',
    hot: true,
    conditions: ['已在新就业地参保', '原参保地已停保', '未办理退休手续'],
    timeLimit: '45个工作日',
    charge: '免费',
    window: '综合窗口2号',
    process: [
      { title: '申请受理', desc: '向新参保地社保机构提出转移申请，或线上提交' },
      { title: '联系函', desc: '新参保地发出联系函至原参保地' },
      { title: '信息表回传', desc: '原参保地办理并回传《基本养老保险参保缴费信息表》' },
      { title: '基金转移', desc: '转移个人账户与统筹基金' },
      { title: '办结确认', desc: '新参保地办结并告知申请人' }
    ],
    materials: [
      { name: '居民身份证', required: true, copies: '原件+复印件1份', sample: '身份证正反面复印件', note: '在有效期内' },
      { name: '养老保险参保缴费凭证', required: true, copies: '1份', sample: '原参保地打印', note: '线上可自助打印' },
      { name: '转移接续申请表', required: true, copies: '1份', sample: '现场或线上填写', note: '' }
    ],
    notice: '建议在停保后6个月内办理，避免影响待遇领取。'
  },
  {
    id: 3,
    code: 'GA-SFZ-003',
    name: '居民身份证申领、换领、补领',
    deptId: 2,
    category: '公安户政',
    serviceObject: '本市户籍及异地常住人员',
    legalBasis: '《中华人民共和国居民身份证法》',
    hot: true,
    conditions: ['年满16周岁或未满16周岁由监护人陪同', '人像、指纹采集符合要求'],
    timeLimit: '15个工作日（加急7个工作日）',
    charge: '首次免费；换领20元；补领40元',
    window: '户政窗口1号、2号',
    process: [
      { title: '预约取号', desc: '线上预约或现场取号' },
      { title: '人像指纹采集', desc: '采集人像、指纹信息' },
      { title: '受理确认', desc: '核对信息并缴费' },
      { title: '制证发证', desc: '凭回执领证或邮寄送达' }
    ],
    materials: [
      { name: '居民户口簿', required: true, copies: '原件', sample: '户口簿', note: '本市户籍' },
      { name: '原居民身份证', required: false, copies: '原件', sample: '换领/补领时提供', note: '丢失可书面声明' },
      { name: '居住证', required: false, copies: '原件', sample: '异地办理时提供', note: '' }
    ],
    notice: '异地办理需提供有效居住证或在读证明。'
  },
  {
    id: 4,
    code: 'GA-JZZ-004',
    name: '居住证办理',
    deptId: 2,
    category: '公安户政',
    serviceObject: '非本市户籍常住人员',
    legalBasis: '《居住证暂行条例》',
    hot: false,
    conditions: ['在本市稳定居住满半年', '有合法稳定就业、住所或连续就读之一'],
    timeLimit: '15个工作日',
    charge: '免费',
    window: '户政窗口1号',
    process: [
      { title: '申报登记', desc: '到居住地派出所申报居住登记' },
      { title: '提交材料', desc: '满半年后提交居住证申请材料' },
      { title: '审核', desc: '派出所审核' },
      { title: '领证', desc: '审核通过后制发居住证' }
    ],
    materials: [
      { name: '居民身份证', required: true, copies: '原件+复印件1份', sample: '身份证正反面复印件', note: '' },
      { name: '居住证明', required: true, copies: '1份', sample: '租赁合同/房产证', note: '' },
      { name: '就业/就读证明', required: true, copies: '1份', sample: '劳动合同或学籍证明', note: '三选一' },
      { name: '居住证申领表', required: true, copies: '1份', sample: '现场填写', note: '可线上预填' }
    ],
    notice: '居住证每年需办理签注。'
  },
  {
    id: 5,
    code: 'SC-YYZZ-005',
    name: '个体工商户营业执照办理',
    deptId: 3,
    category: '市场监管',
    serviceObject: '个体工商户经营者',
    legalBasis: '《个体工商户条例》',
    hot: true,
    conditions: ['年满18周岁具有完全民事行为能力', '有合法的经营场所'],
    timeLimit: '3个工作日',
    charge: '免费',
    window: '市场监管窗口',
    process: [
      { title: '名称核准', desc: '线上提交名称预先核准' },
      { title: '提交申请', desc: '提交设立登记材料' },
      { title: '审核发照', desc: '审核通过后发放电子/纸质营业执照' }
    ],
    materials: [
      { name: '经营者身份证', required: true, copies: '原件+复印件1份', sample: '身份证正反面复印件', note: '' },
      { name: '经营场所证明', required: true, copies: '1份', sample: '租赁合同或产权证明', note: '' },
      { name: '名称预先核准通知书', required: false, copies: '1份', sample: '线上自动生成', note: '无名称可不提供' }
    ],
    notice: '支持全程电子化办理，无需到现场。'
  },
  {
    id: 6,
    code: 'GJJ-TQ-006',
    name: '住房公积金提取（租房）',
    deptId: 4,
    category: '公积金',
    serviceObject: '本市缴存职工',
    legalBasis: '《住房公积金管理条例》',
    hot: true,
    conditions: ['连续足额缴存满3个月', '本人及配偶在本市无自有住房', '租赁住房用于自住'],
    timeLimit: '3个工作日',
    charge: '免费',
    window: '公积金窗口',
    process: [
      { title: '线上申请', desc: '公积金APP或官网提交提取申请' },
      { title: '联网核查', desc: '核查缴存与租房信息' },
      { title: '资金划转', desc: '审核通过后划转至本人银行卡' }
    ],
    materials: [
      { name: '居民身份证', required: true, copies: '原件', sample: '身份证', note: '' },
      { name: '婚姻关系证明', required: false, copies: '1份', sample: '已婚提供结婚证', note: '' },
      { name: '租赁合同', required: false, copies: '1份', sample: '无房提取可免', note: '按实际情形提供' }
    ],
    notice: '每年可提取一次，提取额度按规定执行。'
  },
  {
    id: 7,
    code: 'GA-XSE-007',
    name: '新生儿出生登记（落户）',
    deptId: 2,
    category: '公安户政',
    serviceObject: '新生儿父母',
    legalBasis: '《中华人民共和国户口登记条例》',
    hot: false,
    conditions: ['婴儿出生未满1周岁', '父母至少一方为本市户籍或持有效居住证'],
    timeLimit: '即办即结',
    charge: '免费',
    window: '户政窗口1号',
    process: [
      { title: '提交材料', desc: '携带材料到户籍地或居住地派出所' },
      { title: '受理登记', desc: '当场受理并录入户口信息' },
      { title: '打印户口簿', desc: '打印新生儿户口页' }
    ],
    materials: [
      { name: '出生医学证明', required: true, copies: '原件', sample: '医院出具', note: '' },
      { name: '父母身份证', required: true, copies: '原件+复印件1份', sample: '身份证正反面复印件', note: '' },
      { name: '结婚证', required: false, copies: '原件', sample: '已婚提供', note: '' },
      { name: '落户地户口簿', required: true, copies: '原件', sample: '户口簿', note: '' }
    ],
    notice: '超过1周岁未落户的按补录程序办理。'
  },
  {
    id: 8,
    code: 'ZR-BDC-008',
    name: '不动产登记（商品房买卖转移）',
    deptId: 6,
    category: '不动产',
    serviceObject: '房屋买卖双方',
    legalBasis: '《不动产登记暂行条例》',
    hot: false,
    conditions: ['房屋已办理首次登记', '买卖双方共同申请', '相关税费已缴清'],
    timeLimit: '5个工作日',
    charge: '登记费按规收取',
    window: '不动产登记窗口',
    process: [
      { title: '网签备案', desc: '签订买卖合同并网签备案' },
      { title: '缴税', desc: '缴纳税费' },
      { title: '申请登记', desc: '提交转移登记申请' },
      { title: '审核发证', desc: '审核通过后发放不动产权证书' }
    ],
    materials: [
      { name: '买卖合同', required: true, copies: '原件1份', sample: '网签合同', note: '' },
      { name: '身份证明', required: true, copies: '买卖双方原件', sample: '身份证/营业执照', note: '' },
      { name: '完税凭证', required: true, copies: '1份', sample: '税务出具', note: '' },
      { name: '原不动产权证书', required: true, copies: '原件', sample: '房产证', note: '' }
    ],
    notice: '可预约办理，减少排队等待。'
  },
  {
    id: 9,
    code: 'JJ-JSZ-009',
    name: '机动车驾驶证期满换证',
    deptId: 7,
    category: '交管',
    serviceObject: '驾驶证持有人',
    legalBasis: '《机动车驾驶证申领和使用规定》',
    hot: true,
    conditions: ['驾驶证有效期满前90日内', '身体条件符合要求', '无未处理的交通违法'],
    timeLimit: '即办即结（或邮寄3个工作日）',
    charge: '工本费10元',
    window: '车驾管窗口',
    process: [
      { title: '体检', desc: '到指定医疗机构体检' },
      { title: '提交申请', desc: '线上或窗口提交换证申请' },
      { title: '制证', desc: '现场制证或邮寄送达' }
    ],
    materials: [
      { name: '居民身份证', required: true, copies: '原件', sample: '身份证', note: '' },
      { name: '原驾驶证', required: true, copies: '原件', sample: '驾驶证', note: '' },
      { name: '身体条件证明', required: true, copies: '1份', sample: '体检医院出具', note: '可电子化' },
      { name: '一寸白底彩照', required: true, copies: '2张', sample: '近期照片', note: '' }
    ],
    notice: '可通过“交管12123”APP全程线上办理。'
  },
  {
    id: 10,
    code: 'MZ-LN-010',
    name: '老年人优待证办理',
    deptId: 5,
    category: '民政',
    serviceObject: '年满60周岁本市居民',
    legalBasis: '《中华人民共和国老年人权益保障法》',
    hot: false,
    conditions: ['年满60周岁', '为本市户籍'],
    timeLimit: '即办即结',
    charge: '免费',
    window: '民政窗口',
    process: [
      { title: '提交申请', desc: '持身份证到社区或民政窗口申请' },
      { title: '审核', desc: '核实年龄与户籍' },
      { title: '发证', desc: '当场发放优待证' }
    ],
    materials: [
      { name: '居民身份证', required: true, copies: '原件+复印件1份', sample: '身份证正反面复印件', note: '' },
      { name: '一寸照片', required: true, copies: '1张', sample: '近期免冠照', note: '' }
    ],
    notice: '可委托他人代办，需提供代办人身份证。'
  }
]

// 知识库文档（五类）
export const knowledgeDocs = [
  { id: 1, title: '社会保障卡申领办事指南', type: '办事指南', deptId: 1, itemId: 1, content: '社会保障卡申领办理条件、材料与流程……' },
  { id: 2, title: '《社会保险法》节选', type: '政策文件', deptId: 1, itemId: 2, content: '基本养老保险关系转移相关政策条款……' },
  { id: 3, title: '身份证申领材料模板', type: '材料模板', deptId: 2, itemId: 3, content: '居民身份证申领登记表填写样例……' },
  { id: 4, title: '营业执照办理常见问题', type: '常见问题', deptId: 3, itemId: 5, content: '个体工商户设立常见问答……' },
  { id: 5, title: '公积金租房提取FAQ', type: '常见问题', deptId: 4, itemId: 6, content: '公积金租房提取常见问答……' },
  { id: 6, title: '政务大厅窗口信息一览', type: '窗口信息', deptId: null, itemId: null, content: '各窗口地址、电话、服务时间……' }
]

// 办件记录
export const cases = [
  { id: 1, itemId: 1, itemName: '社会保障卡申领', applicant: '张三', phone: '13900000001', idCard: '3401********1234', status: '办理中', materials: ['居民身份证', '社保卡申领登记表'], submitTime: '2026-08-12 09:30', staffId: 1, windowId: 1, result: '' },
  { id: 2, itemId: 2, itemName: '养老保险关系转移接续', applicant: '李四', phone: '13900000002', idCard: '3401********5678', status: '待审核', materials: ['居民身份证', '养老保险参保缴费凭证'], submitTime: '2026-08-15 14:20', staffId: 2, windowId: 2, result: '' },
  { id: 3, itemId: 3, itemName: '居民身份证换领', applicant: '王五', phone: '13900000003', idCard: '3401********9012', status: '已办结', materials: ['居民户口簿', '原居民身份证'], submitTime: '2026-08-10 10:00', staffId: 3, windowId: 3, result: '制证完成，已通知领取' },
  { id: 4, itemId: 5, itemName: '个体工商户营业执照办理', applicant: '赵六', phone: '13900000004', idCard: '3401********3456', status: '办理中', materials: ['经营者身份证', '经营场所证明'], submitTime: '2026-08-16 11:00', staffId: 5, windowId: 5, result: '' },
  { id: 5, itemId: 6, itemName: '住房公积金提取（租房）', applicant: '钱七', phone: '13900000005', idCard: '3401********7890', status: '已办结', materials: ['居民身份证'], submitTime: '2026-08-14 16:40', staffId: 6, windowId: 6, result: '资金已划转' }
]

// 群众咨询记录
export const consultations = [
  { id: 1, user: '张三', question: '社保转移需要什么材料？', itemId: 2, status: '已答复', satisfaction: 5, time: '2026-08-15 10:12', handledBy: 'AI助手' },
  { id: 2, user: '李四', question: '身份证丢了怎么补办？', itemId: 3, status: '已答复', satisfaction: 4, time: '2026-08-15 11:30', handledBy: 'AI助手' },
  { id: 3, user: '王五', question: '营业执照几天能办好？', itemId: 5, status: '转人工', satisfaction: 3, time: '2026-08-16 09:05', handledBy: '刘芳' },
  { id: 4, user: '赵六', question: '公积金租房怎么提取？', itemId: 6, status: '已答复', satisfaction: 5, time: '2026-08-16 14:22', handledBy: 'AI助手' },
  { id: 5, user: '钱七', question: '居住证办理需要什么条件？', itemId: 4, status: '已答复', satisfaction: 4, time: '2026-08-17 08:50', handledBy: 'AI助手' }
]

// 常见问题（问答引擎匹配用）
export const faq = [
  { q: '社保转移', itemId: 2, answer: '养老保险关系转移接续需提供：居民身份证、养老保险参保缴费凭证、转移接续申请表。请到综合窗口2号办理，全程免费，办理时限45个工作日。' },
  { q: '身份证', itemId: 3, answer: '居民身份证补领需携带居民户口簿到户政窗口办理，补领费用40元，15个工作日内办结，可加急7个工作日。' },
  { q: '营业执照', itemId: 5, answer: '个体工商户营业执照支持全程电子化办理，需提供经营者身份证和经营场所证明，3个工作日内审核发照，免费。' },
  { q: '公积金', itemId: 6, answer: '租房提取公积金需连续足额缴存满3个月且本人及配偶在本市无自有住房，可通过公积金APP线上申请，3个工作日划转到账。' },
  { q: '居住证', itemId: 4, answer: '办理居住证需在本市稳定居住满半年，且有合法稳定就业、住所或连续就读之一，携带身份证、居住证明、就业或就读证明到户政窗口办理。' }
]

export const categoryOptions = ['社会保障', '公安户政', '市场监管', '公积金', '民政', '不动产', '交管']
export const caseStatusOptions = ['待审核', '办理中', '已办结', '已驳回']
export const docTypeOptions = ['办事指南', '政策文件', '材料模板', '常见问题', '窗口信息']
